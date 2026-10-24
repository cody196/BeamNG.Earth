"""navgraph: the drivable roads as the stock map's graph: connectors shared at junctions, one-way direction,
lanes, speed limits, clipped to the window."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import navgraph  # noqa: E402
import roads  # noqa: E402
from test_roads import FRAME, features, flat, rules  # noqa: E402


def graph(lines, classes, connectors=(), oneway=(), speeds=(), subclass=(), centre=(0.0, 0.0), window=1100.0):
    f = features(lines, classes)
    f.rules["connectors"] = rules(list(connectors))
    f.rules["oneway"] = rules(list(oneway), "float")
    f.rules["max_speed_kmh"] = rules(list(speeds), "float")
    f.rules["subclass"] = rules(list(subclass))
    return navgraph.build(FRAME, [f], flat, centre, window=window)


class GraphTest(unittest.TestCase):
    def test_junction_shares_the_connector(self):
        g = graph([[(0, 0), (100, 0)], [(100, 0), (100, 100)]], ["residential", "residential"],
                  connectors=[(0, "A", 0.0, 0.0), (0, "J", 1.0, 1.0), (1, "J", 0.0, 0.0), (1, "B", 1.0, 1.0)])
        self.assertIn("cJ", g["nodes"])
        links = [e for e in g["edges"] if "cJ" in e[:2]]
        self.assertEqual(len(links), 2, "both roads end at the junction node")
        x, y, z, r = g["nodes"]["cJ"]
        self.assertAlmostEqual(x, 100.0, delta=0.5)
        self.assertAlmostEqual(y, 0.0, delta=0.5)
        self.assertEqual(z, 10.0)
        for e in g["edges"]:
            self.assertEqual((e[3], e[4]), (1, 1), "a two-way residential street: one lane each way")
            self.assertAlmostEqual(e[5], 25 * navgraph.MPH, places=2)

    def test_long_edges_split_and_oneway_against_the_geometry(self):
        g = graph([[(0, 0), (300, 0)]], ["secondary"], connectors=[(0, "A", 0.0, 0.0), (0, "B", 1.0, 1.0)],
                  oneway=[(0, -1.0)], speeds=[(0, 72.0)])
        self.assertGreaterEqual(len(g["edges"]), 4, "300 m in edges of at most MAX_EDGE_M")
        for e in g["edges"]:
            self.assertEqual(e[2], 1)
            self.assertLess(g["nodes"][e[1]][0], g["nodes"][e[0]][0], "one-way -1: drives against the geometry")
            self.assertEqual((e[3], e[4]), (e[3], 0))
            self.assertAlmostEqual(e[5], 20.0, places=2)
        self.assertTrue(any(e[1] == "cA" for e in g["edges"]))

    def test_not_drivable_and_window(self):
        g = graph([[(0, 0), (50, 0)], [(0, 10), (50, 10)], [(0, 20), (50, 20)], [(5000, 0), (5100, 0)]],
                  ["footway", "service", "residential", "residential"], subclass=[(1, "parking_aisle")])
        ys = {round(n[1]) for n in g["nodes"].values()}
        self.assertEqual(ys, {20}, "only the residential street in the window")

    def test_even_lanes_and_no_parking_lanes(self):
        import roads
        for cls in ("residential", "tertiary", "secondary", "primary"):
            sp = roads.Spec(roads.carriageway(cls, "paved", True), "paved", True, cls, False)
            w = navgraph.driving_width(sp)
            self.assertLessEqual(w, sp.width)
            lo, li = navgraph._lanes(w, False)
            self.assertEqual(lo, li, cls)

    def test_rural_motorway_two_lanes(self):
        import roads
        for urban, n in ((False, 2), (True, 3)):
            sp = roads.Spec(roads.carriageway("motorway", "paved", urban, None, True), "paved", urban, "motorway", True)
            self.assertEqual(navgraph._lanes(navgraph.driving_width(sp), True), (n, 0), urban)
        ramp = roads.Spec(roads.LINK_M[1], "paved", False, "motorway", True)
        self.assertEqual(navgraph._lanes(navgraph.driving_width(ramp), True), (1, 0), "a ramp: one lane (GitHub #107)")

    def test_tunnel_stretch_left_out(self):
        f = features([[(0, 0), (300, 0)]], ["primary"], levels=[(0, -1.0, 0.4, 0.7)])
        f.rules["connectors"] = rules([(0, "A", 0.0, 0.0), (0, "B", 1.0, 1.0)])
        g = navgraph.build(FRAME, [f], flat, (0.0, 0.0))
        for e in g["edges"]:
            mid = (g["nodes"][e[0]][0] + g["nodes"][e[1]][0]) / 2
            self.assertFalse(130 < mid < 200, "an edge over the tunnel")
        self.assertTrue(g["edges"])

    def test_nodes_on_a_bridge_take_its_deck(self):
        f = features([[(0, 0), (200, 0)]], ["primary"])
        f.rules["connectors"] = rules([(0, "A", 0.0, 0.0), (0, "B", 1.0, 1.0)])
        decks = {"id000": [(np.array([(50.0, 0.0), (150.0, 0.0)]), np.array([10.0, 14.0]))]}
        g = navgraph.build(FRAME, [f], flat, (0.0, 0.0), decks=decks)
        on = [n for n in g["nodes"].values() if 55 < n[0] < 145]
        off = [n for n in g["nodes"].values() if n[0] < 40 or n[0] > 160]
        self.assertTrue(on and off)
        for n in on:
            self.assertAlmostEqual(n[2], 10.0 + 4.0 * (n[0] - 50.0) / 100.0, delta=0.05)
        self.assertTrue(all(n[2] == 10.0 for n in off), "the ground (flat 10 m) off the bridge")

    def test_ground_nodes_follow_local_height_far_from_anchor(self):
        # A constant geographic elevation is NOT a flat plane in the game's frame.
        # At ~8 km the former raw-elevation nodes trip Autodrive's 5 m deck guard.
        for cx, cy in ((0, 0), (0, 8170), (20000, 0), (0, -20000)):
            with self.subTest(centre=(cx, cy)):
                f = features([[(cx-150, cy), (cx+150, cy)]], ['motorway'])
                elev = lambda la, lo: np.full(np.shape(la), 303.12)
                g = navgraph.build(FRAME, [f], elev, (cx, cy))
                self.assertGreater(len(g['nodes']), 2)
                for x, y, z, _ in g['nodes'].values():
                    surface_z = float(FRAME.surface_enu(x, y, elev)[5])
                    self.assertAlmostEqual(z, surface_z, delta=0.015,
                                           msg='graph and physical ground must share the ENU frame')
                if cy == 8170:
                    self.assertTrue(all(303.12-n[2] > 5 for n in g['nodes'].values()))

    def test_bridge_heights_are_not_converted_twice_far_from_anchor(self):
        f = features([[(-150, 20000), (150, 20000)]], ['motorway'])
        xy = np.column_stack(FRAME.geodetic_to_enu(f.lonlat[:, 1], f.lonlat[:, 0], 0))[:, :2]
        deck_z = 280.5  # bridge builder already returns local ENU up
        decks = {'id000': [(xy, np.full(len(xy), deck_z))]}
        g = navgraph.build(FRAME, [f], lambda la, lo: np.full(np.shape(la), 303.12),
                           (0, 20000), decks=decks)
        self.assertGreater(len(g['nodes']), 2)
        self.assertTrue(all(n[2] == deck_z for n in g['nodes'].values()),
                        'do not apply the curvature correction again to bridge profiles')

    def test_ground_height_respects_anchor_altitude(self):
        import geodesy
        elevated = geodesy.EnuFrame(FRAME.lat0, FRAME.lon0, 100)
        f = features([[(0, 0), (150, 0)]], ['primary'])
        g = navgraph.build(elevated, [f], lambda la, lo: np.full(np.shape(la), 303.12), (0, 0))
        self.assertTrue(g['nodes'])
        self.assertTrue(all(abs(n[2]-203.12) < 0.02 for n in g['nodes'].values()))



class SignalsTest(unittest.TestCase):
    def test_no_stop_on_a_link_inside_one_intersection(self):
        import roads
        sp = roads.Spec(8.0, "paved", True, "residential", False)
        nodes = {"cJ": [0.0, 0.0, 0.0, 4], "cK": [0.0, 8.0, 0.0, 4], "s1": [0.0, -40.0, 0.0, 2],
                 "cW": [-40.0, 0.0, 0.0, 2], "cE": [40.0, 0.0, 0.0, 2]}
        arms = {"cJ": [("n", sp, np.array([0.0, 1.0]), 0.0, 1), ("s", sp, np.array([0.0, -1.0]), 0.0, 0),
                       ("w", sp, np.array([-1.0, 0.0]), 0.0, 1), ("e", sp, np.array([1.0, 0.0]), 0.0, 0)]}
        approaches = {("cJ", "n", 1): ("cK", True), ("cJ", "s", 0): ("s1", True), ("cJ", "w", 1): ("cW", True),
                      ("cJ", "e", 0): ("cE", True)}
        import furniture
        orig = furniture.junction_controls
        furniture.junction_controls = lambda a, k, link_ok=None, ring=None: [(x, furniture.G_STOP) for x in a]     # an all-way stop
        try:
            out = navgraph._signals(arms, approaches, nodes)
        finally:
            furniture.junction_controls = orig
        got = {ap[0] for ap in out[0]["app"]}
        self.assertEqual(got, {"s1", "cW", "cE"}, "the 8 m link from the next connector gets no stop")


class RulesTest(unittest.TestCase):
    def test_default_speeds_by_country(self):
        class F:            # a feature without a mapped limit
            rules = {}
        mw = roads.Spec(11.0, "paved", False, "motorway", True)
        self.assertAlmostEqual(navgraph.road_mph(F, 0, mw), 65.0)
        self.assertAlmostEqual(navgraph.road_mph(F, 0, mw, mph=False) * 1.609344, 120.0)
        town = roads.Spec(9.0, "paved", True, "primary", False)
        self.assertAlmostEqual(navgraph.road_mph(F, 0, town, mph=False), 35.0, msg="in town: the urban cap")
        res = roads.Spec(6.0, "paved", True, "residential", False)
        self.assertAlmostEqual(navgraph.road_mph(F, 0, res, mph=False), 25.0)

    def test_driving_side_and_signals_by_country(self):
        self.assertEqual(navgraph.road_rules("US"), {"rightHandDrive": False, "turnOnRed": True, "redYellow": False,
                                                     "country": "US", "mph": True})
        self.assertFalse(navgraph.road_rules("CH")["mph"])
        self.assertTrue(navgraph.road_rules("GB")["mph"])
        self.assertTrue(navgraph.road_rules("gb")["rightHandDrive"], "the game's name: true = driving on the left")
        self.assertTrue(navgraph.road_rules("GB")["redYellow"])
        self.assertFalse(navgraph.road_rules("DE")["rightHandDrive"])
        self.assertTrue(navgraph.road_rules("JP")["rightHandDrive"])
        self.assertFalse(navgraph.road_rules(None)["rightHandDrive"], "unknown: US rules")


if __name__ == "__main__":
    unittest.main()
