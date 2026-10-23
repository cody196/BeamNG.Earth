"""Road-aware loading follows bends/direction/topology and refills without waiting for poses."""
import asyncio
from concurrent.futures import CancelledError
from pathlib import Path
import sys
import tempfile
import threading
import unittest

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import blockworker
import roadahead
import roads
from test_roads import FRAME, features, rules


class RoadLookaheadTest(unittest.TestCase):
    def test_follows_curved_highway_and_requests_tiles_around_the_bend(self):
        f = features([[(0., 0.), (500., 0.), (900., 300.), (900., 1800.)]], ["motorway"])
        f.rules["oneway"] = rules([(0, 1.)], "float")
        path = roadahead.trace(FRAME, [f], 100., 0., 80., 0., 2200.)
        self.assertGreater(path[-1][1], 1400.)
        self.assertAlmostEqual(path[-1][0], 900., delta=10.)
        want = roads.wanted_tiles(100., 0., 80., 0., path)
        self.assertIn((3, 5), want)
        self.assertNotIn((8, 0), want)
        key = roads.path_key(100., 0., 80., 0., path)
        self.assertLess(key((3, 4)), key((8, 0)))

    def test_never_turns_onto_an_overpass_without_shared_connector(self):
        f = features([[(0., 0.), (600., 0.)], [(600., -1000.), (600., 2000.)]], ["motorway"]*2)
        path = roadahead.trace(FRAME, [f], 100., 0., 80., 0., 2200.)
        self.assertLess(abs(path[-1][1]), 5.)
        self.assertAlmostEqual(path[-1][0], 600., delta=5.)

    def test_prefers_mainline_at_a_mapped_exit_and_can_follow_a_connected_turn(self):
        f = features([[(0., 0.), (500., 0.)], [(500., 0.), (1400., 500.)],
                      [(500., 0.), (1500., 100.)]], ["motorway"]*3)
        f.rules["connectors"] = rules([(0, "join", 1., 1.), (1, "join", 0., 0.), (2, "join", 0., 0.)])
        f.rules["subclass"] = rules([(2, "link")])
        f.rules["oneway"] = rules([(i, 1.) for i in range(3)], "float")
        path = roadahead.trace(FRAME, [f], 100., 0., 80., 0., 1800.)
        self.assertGreater(path[-1][1], 450.)
        # A sole right-angle continuation is still connected (not a straight-line guess).
        turn = features([[(0., 0.), (500., 0.)], [(500., 0.), (500., 1200.)]], ["primary"]*2)
        turn.rules["connectors"] = rules([(0, "j", 1., 1.), (1, "j", 0., 0.)])
        path = roadahead.trace(FRAME, [turn], 100., 0., 30., 0., 1600.)
        self.assertGreater(path[-1][1], 1100.)

    def test_matches_correct_carriageway_direction(self):
        f = features([[(0., 0.), (2000., 0.)], [(0., 15.), (2000., 15.)]], ["motorway"]*2)
        f.rules["oneway"] = rules([(0, -1.), (1, 1.)], "float")
        path = roadahead.trace(FRAME, [f], 100., 2., 80., 0., 1500.)
        self.assertAlmostEqual(path[-1][1], 15., delta=5.)
        self.assertGreater(path[-1][0], 1500.)

    def test_missing_cached_cells_never_start_a_network_read(self):
        class Md:
            def has(self, *args): return False
            def cell(self, *args, **kwargs): raise AssertionError("uncached source fetched")
        planner = roadahead.Planner(Md(), 6000.)
        self.assertEqual(planner._plan(FRAME, 0., 0., 80., 0., ()), ())
        planner.pool.shutdown()

    def test_moved_far_off_path_discards_old_hint(self):
        self.assertEqual(roadahead.remaining(((0., 0.), (1000., 0.)), 200., 200.), ())
        trimmed = roadahead.remaining(((0., 0.), (1000., 0.), (1000., 1000.)), 600., 1.)
        self.assertGreaterEqual(trimmed[1][0], 599.)

    def test_teleport_cancels_worker_before_it_reads_source_cells(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "cancel_roads_4").touch()
            with self.assertRaises(CancelledError):
                blockworker.road_checkpoint(root, 4)
            with self.assertRaises(CancelledError):
                blockworker.build(4, 0., 0., 15, .03125, 0., 0., 512, root, "old.png")
            blockworker.road_checkpoint(root, 5)


class RoadPumpTest(unittest.TestCase):
    def test_one_pose_drains_nearby_work_without_another_pose(self):
        async def run():
            tracker, built, done = roads.Tracker(), [], asyncio.Event()
            wanted = set(roads.tiles_near(0., 0., roads.SEND_M))
            class Conn:
                def send(self, msg):
                    if len(tracker.sent) == len(wanted): done.set()
            def build(aid, x, y):
                built.append((x, y))
                return "/road", 1
            tracker.on_pose(Conn(), 1, 0., 0., asyncio.get_running_loop(), build)
            try:
                await asyncio.wait_for(done.wait(), 2.)
                self.assertEqual(set(built), wanted)
                self.assertEqual(len(built), len(wanted))
            finally:
                tracker.close()
        asyncio.run(run())

    def test_suspended_location_does_not_refill_cancelled_work(self):
        async def run():
            tracker, built, release = roads.Tracker(), [], threading.Event()
            class Conn:
                def send(self, msg): pass
            def build(aid, x, y):
                built.append((x, y))
                release.wait(2.)
                raise CancelledError()
            tracker.on_pose(Conn(), 1, 0., 0., asyncio.get_running_loop(), build)
            tracker.suspend()
            release.set()
            await asyncio.sleep(.1)
            self.assertLessEqual(len(built), roads.BUILD_PER_POSE)
            self.assertIsNone(tracker._latest)
            tracker.close()
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
