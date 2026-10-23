"""Loading regressions: long highways, concurrent ramp builds and local road painting."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import roads
import surface
from test_roads import FRAME, features, rules
from test_auxiliary_markings import interchange


def exhaustive_nearest(points, lines):
    """Reference distance projection without the optimized search window."""
    best = np.full(len(points), np.inf)
    result, widths, owners = np.zeros((len(points), 5)), np.zeros(len(points)), np.zeros(len(points), int)
    for owner, (line, width) in enumerate(lines):
        a, ab = line[:-1], np.diff(line, axis=0)
        t = np.clip(((points[:, None, :2]-a[:, :2])*ab[:, :2]).sum(2)
                    / np.maximum((ab[:, :2]**2).sum(1), 1e-12), 0., 1.)
        d = ((points[:, None, :2]-a[:, :2]-t[..., None]*ab[:, :2])**2).sum(2)
        k = d.argmin(1)
        dist = d[np.arange(len(points)), k]
        use = dist < best
        result[use] = a[k[use]]+t[use, k[use], None]*ab[k[use]]
        widths[use] = (np.interp(k[use]+t[use, k[use]], np.arange(len(line)), width)
                       if np.ndim(width) else width)
        owners[use], best[use] = owner, dist[use]
    return result, widths, owners


class RoadLoadingTest(unittest.TestCase):
    def test_clipped_highway_keeps_full_road_cross_sections_in_both_directions(self):
        x = np.linspace(0., 1000., 1001)
        p = np.c_[x, 100*np.sin(x/300.), np.zeros(len(x))]
        normal = roads.offset_polyline(p, 1.)[:, :2]-p[:, :2]
        sections = {tuple(np.rint(point[:2]*2).astype(int)): [(point[:2], cross, False)]
                    for point, cross in zip(p, normal)}
        for direction in (1, -1):
            part = p[100:-100][::direction]
            got = roads._with_cross(part, sections)
            np.testing.assert_allclose(got[:, :3], part, atol=1e-12)
            np.testing.assert_allclose(got[:, 3:5], normal[100:-100][::direction]*direction, atol=1e-12)

    def test_road_and_bridge_reuse_widths_without_leaking_ground_filter(self):
        f = features([[(0., 0.), (100., 0.)], [(0., 20.), (100., 20.)]], ['motorway']*2)
        f.rules['level'] = rules([(1, 1.)], 'float')
        with patch.object(roads, '_full_road_specs', wraps=roads._full_road_specs) as build:
            ground = roads.road_specs(f)
            bridges = roads.bridge_specs(f)
            self.assertIsNone(ground[1])
            self.assertIsNotNone(bridges[1])
            self.assertEqual(build.call_count, 1)
            roads._road_specs(f, None, None, True, include_bridges=True)
            self.assertEqual(build.call_count, 2, 'driving side has its own widths')

    def test_long_road_projection_matches_exhaustive_search_and_variable_widths(self):
        x = np.linspace(-15000., 15000., 12001)
        a = np.c_[x, 80*np.sin(x/400), np.zeros(len(x)), np.zeros(len(x)), np.ones(len(x))]
        b = a.copy()
        b[:, 1] += 35.
        widths = 4.+np.arange(len(x))/len(x)*4.
        # Include widely spread queries, a reversed line, and a segment whose
        # endpoints lie outside the query box but which crosses through it.
        points = np.array([[14000., 100.], [0., 12.], [-50., -10.], [500., 20.], [-14000., -50.]])
        crossing = np.array([[-20000., 0., 0., 0., 1.], [20000., 0., 0., 0., 1.]])
        for queries in (points, points[1:4], np.empty((0, 2))):
            lines = [(a, widths), (b[::-1], 6.), (crossing, 3.)]
            actual = roads._nearest_road(queries, lines, with_owner=True)
            expected = exhaustive_nearest(queries, lines) if len(queries) else actual
            for got, want in zip(actual, expected):
                np.testing.assert_allclose(got, want, atol=1e-10)

    def test_concurrent_ramp_requests_build_one_complete_layout(self):
        f = interchange()
        entered, release = threading.Event(), threading.Event()
        original = roads._ramp_markings
        def calculate(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('test did not release ramp computation')
            return original(*args, **kwargs)
        with patch.object(roads, '_ramp_markings', side_effect=calculate) as build, ThreadPoolExecutor(2) as pool:
            first = pool.submit(roads.cached_ramp_layout, f)
            try:
                self.assertTrue(entered.wait(2))
                second = pool.submit(roads.cached_ramp_layout, f)
            finally:
                release.set()
            self.assertIs(first.result(timeout=2), second.result(timeout=2))
        self.assertEqual(build.call_count, 1)

    def test_local_corner_paint_matches_full_source_and_ignores_distant_junctions(self):
        main = [(x, 100.) for x in np.arange(-15000., 15001., 100.)]
        f = features([main, [(100., 100.), (100., 280.)],
                      [(12000., 100.), (12000., 280.)]], ['primary', 'motorway', 'motorway'])
        f.rules['oneway'] = rules([(1, -1.), (2, -1.)], 'float')
        f.rules['subclass'] = rules([(1, 'link'), (2, 'link')])
        full = roads.ground_corners(FRAME, [f])
        with patch.object(roads, 'ground_corners', return_value=full):
            reference = surface._corner_mask(FRAME, 0., 0., 320., 320, 320, [f])
        with patch.object(roads.junctions, 'find', wraps=roads.junctions.find) as find:
            actual = surface._corner_mask(FRAME, 0., 0., 320., 320, 320, [f])
        np.testing.assert_array_equal(actual, reference)
        self.assertTrue(actual.any())
        for call in find.call_args_list:
            points = np.concatenate([row[2] for row in call.args[0]])
            self.assertLess(np.abs(points[:, :2]).max(), 1000.)

    def test_local_windows_keep_reentry_runs_and_original_samples(self):
        p = np.array([[-20., 0.], [0., 0.], [20., 0.], [20., 40.], [0., 40.],
                      [0., 0.], [-20., 0.]])
        runs = roads._nearby_runs(p, (-5., -5., 5., 5.))
        self.assertEqual(len(runs), 2)
        np.testing.assert_array_equal(runs[0], p[:3])
        np.testing.assert_array_equal(runs[1], p[4:])


if __name__ == '__main__':
    unittest.main()
