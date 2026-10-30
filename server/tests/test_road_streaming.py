"""Cold road cells are prepared once; highway builds reach past the surrounding disc."""
import json
import sys
import threading
import unittest
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geodesy
import geotiles
import mapcells
import mapdata
import roadcurves
import roadmesh
import roads
from test_roads import features


class DecodeTest(unittest.TestCase):
    def make_map(self):
        md = mapdata.MapData.__new__(mapdata.MapData)
        md._locks, md._lock = {}, threading.Lock()
        md._mem, md._mem_lock, md._mem_bytes = OrderedDict(), threading.Lock(), 0
        md.pool = ThreadPoolExecutor(8)
        self.addCleanup(md.pool.shutdown)
        md.versions = lambda: {'pipeline': 2}
        f = features([[(0, 0), (100, 0), (200, 45), (300, 50)]], ['motorway'])
        arrays = f.to_arrays('')
        arrays['provenance'] = np.asarray(json.dumps({}))
        md.layer_arrays = lambda *a: (arrays, True)
        return md

    def test_concurrent_cold_requests_share_the_prepared_geometry(self):
        md = self.make_map()
        barrier = threading.Barrier(6)
        original = md.layer_arrays
        def fetch(*args):
            barrier.wait(timeout=10)
            return original(*args)
        md.layer_arrays = fetch
        key = mapcells.cell_of(44.3, -84.4)
        with mock.patch.object(roadcurves, 'prepare', wraps=roadcurves.prepare) as prepare:
            with ThreadPoolExecutor(6) as pool:
                results = list(pool.map(lambda _: md.cell(key, ('roads',)), range(6)))
        self.assertEqual(prepare.call_count, 1)
        self.assertTrue(all(r.layers['roads'] is results[0].layers['roads'] for r in results))
        self.assertTrue(results[0].layers['roads']._curved)
        self.assertEqual(md._locks, {})
        self.assertEqual(len(md._mem), 1)

    def test_failed_preparation_releases_lock_for_retry(self):
        md = self.make_map()
        key = mapcells.cell_of(44.3, -84.4)
        with mock.patch.object(roadcurves, 'prepare', side_effect=ValueError('bad cell')):
            with self.assertRaisesRegex(ValueError, 'bad cell'):
                md.cell(key, ('roads',))
        self.assertEqual(md._locks, {})
        self.assertFalse(md._mem)
        self.assertTrue(md.cell(key, ('roads',)).layers['roads']._curved)


class HighwayLeadTest(unittest.TestCase):
    def test_75mph_builds_a_narrow_forward_corridor(self):
        speed = 75 * 0.44704
        want = roads.wanted_tiles(0, 0, speed, 0)
        self.assertTrue(any(tx * roads.TILE >= 768 for tx, ty in want))
        self.assertFalse(any(ty * roads.TILE >= 1024 for tx, ty in want))

    def test_geo_corridor_extends_at_real_highway_speed(self):
        frame = geodesy.EnuFrame(44.3, -84.4)
        want = roads.geo_wanted(frame, 0, 0, 75 * 0.44704, 0)
        self.assertTrue(any(geotiles.quad(frame, *key)[:, 0].max() >= 1000 for key in want))


class CurveReferenceTest(unittest.TestCase):
    def test_matches_pre_optimization_dense_curves_and_pinned_rules(self):
        with np.load(Path(__file__).parent / 'fixtures' / 'road_curves_reference.npz') as data:
            for name in ('dense2', 'dense3', 'straight', 'duplicate', 'pinned'):
                with self.subTest(name=name):
                    got = roadcurves.rounded(data[name + '_points'], data[name + '_pins'])
                    for i, array in enumerate(got):
                        np.testing.assert_allclose(array, data[f'{name}_out{i}'], rtol=1e-11, atol=1e-8)


class RibbonBatchTest(unittest.TestCase):
    def test_empty_ribbons_do_not_shift_bridge_or_tunnel_ownership(self):
        chunks = [dict(n=points, m='road_asphalt_2lane', w=7, fid=i, **flags)
                  for i, (points, flags) in enumerate([
                      ([(0, 0, 0)], {}),
                      ([(0, 0, 0), (30, 0, 0)], {}),
                      ([(0, 0, 0), (0, 0, 0)], {}),
                      ([(0, 10, 5), (20, 10, 6)], dict(deck=True, fixed=True)),
                      ([(0, 20, 5), (20, 20, 5)], dict(tunnel=True, fixed=True)),
                      ([(0, 30, 0), (1, 30.1, 0), (30, 31, 0)], {}),
                  ])]
        pairs = roadmesh.ribbon_pairs(iter(chunks))
        self.assertEqual([c['fid'] for r, c in pairs], [1, 3, 4, 5])
        for ribbon, owner in pairs:
            self.assertEqual(ribbon[5] is not None, bool(owner.get('fixed')))
            expected = roadmesh.ribbons([owner])[0]
            for got, want in zip(ribbon, expected):
                if isinstance(got, np.ndarray):
                    np.testing.assert_allclose(got, want, rtol=0, atol=1e-12)
                else:
                    self.assertEqual(got, want)

    def test_native_ribbons_are_built_in_one_batch(self):
        import fast
        chunks = [dict(n=[(0, i * 10, 0), (100, i * 10, 0)], m='line_white', w=.12)
                  for i in range(20)]
        with mock.patch.object(fast._ef, 'ribbon_edges', wraps=fast._ef.ribbon_edges) as build:
            self.assertEqual(len(roadmesh.ribbon_pairs(chunks)), 20)
        self.assertEqual(build.call_count, 1)
