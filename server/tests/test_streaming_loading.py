"""Regressions from the 1.6.0 driving/teleport reports. No network or game required."""
import asyncio
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import earthd
import blockworker
import imagery
import mapdata
import netfetch
import staging
import surface


class LoadingRegressionTest(unittest.TestCase):
    def test_provisional_landing_does_not_wait_for_highway_or_lot_fitting(self):
        with tempfile.TemporaryDirectory() as root:
            sf = SimpleNamespace(md=None, classes=lambda lat, lon: (np.full(np.shape(lat), 30, np.uint8), True),
                                 roads=Mock(side_effect=AssertionError('fitting roads during provisional spawn')),
                                 lots=Mock(side_effect=AssertionError('painting lots during provisional spawn')))
            s = earthd.Server(root, str(Path(root, 'cache')), imagery=None, surface=sf, block=512)
            s.dem = SimpleNamespace(sample=lambda lat, lon, *args: np.full(np.shape(lat), 300.))
            anchor = s.new_anchor(41.73844, -84.99996)
            anchor.q = 1/256
            s.anchors[anchor.id] = anchor
            try:
                result = s.make_provisional(anchor, 0., 0., None)
                self.assertTrue(Path(s.out_dir, result['ter']).exists())
                self.assertFalse(result['surfaceComplete'])
                sf.roads.assert_not_called()
                sf.lots.assert_not_called()
            finally:
                s.ahead_planner.close()
                for name in ('tile_pool', 'hm_pool', 'base_pool', 'ahead_pool', 'landing_pool'):
                    getattr(s, name).shutdown(wait=True)

    def test_block_worker_uses_urgent_elevation_and_releases_warmers_after_failure(self):
        state = SimpleNamespace(dem=SimpleNamespace(), cv=threading.Condition(), terrain_busy=0, md=None,
                                surface=None)
        active = []
        @contextmanager
        def urgent():
            active.append(True)
            try:
                yield
            finally:
                active.pop()
        state.dem.urgent = urgent
        def build(*args):
            self.assertTrue(active, 'requested block waited in the ordinary elevation lane')
            self.assertEqual(state.terrain_busy, 1, 'speculative plans can start during terrain build')
            raise RuntimeError('failed terrain')
        with tempfile.TemporaryDirectory() as root, patch.object(blockworker, '_s', state), \
             patch.object(blockworker, '_build', side_effect=build):
            with self.assertRaisesRegex(RuntimeError, 'failed terrain'):
                blockworker.build(1, 41., -85., 16, 1/256, 0., 0., 512, root, 'test.png')
        self.assertFalse(active)
        self.assertEqual(state.terrain_busy, 0)

    def test_sparse_road_samples_do_not_queue_landcover_between_roads(self):
        sf = surface.Surface(Mock())
        raster = SimpleNamespace(sample=lambda lon, lat: np.full(np.shape(lat), 50, np.uint8))
        try:
            with patch.object(sf, '_cached', return_value=raster) as read:
                values, complete = sf.classes(np.array([36.1, 36.25]), np.array([-118., -117.8]))
                np.testing.assert_array_equal(values, [50, 50])
                self.assertTrue(complete)
                self.assertEqual(read.call_count, 2, 'unrelated cells were read/queued')
        finally:
            sf.pool.shutdown()

    def test_curved_road_pose_reaches_road_and_tree_streaming_with_lazy_imagery(self):
        async def run():
            with tempfile.TemporaryDirectory() as root:
                s = earthd.Server(root, str(Path(root, 'cache')), imagery=None, block=512)
                im = imagery.Imagery(str(Path(root, 'imagery')), ('naip', 'usgs'),
                                     fetcher=netfetch.Fetcher(offline=True))
                # Observe the real warm-list calculation without starting downloads.
                im._warm_thread = Mock()
                s.imagery = im
                anchor = s.new_anchor(41.73844, -84.99996)
                s.anchors[anchor.id] = anchor
                conn = earthd.Connection(s, None, Mock())
                conn.active = anchor.id
                path = ((0., 0.), (300., 0.), (600., 300.), (600., 2000.))
                s.ahead_planner.close()
                s.ahead_planner = SimpleNamespace(get=lambda *args: path)
                s.mapdata = object()
                s.veg = Mock()
                s.buildings = False
                s.warm_roads = Mock()
                s.download_ahead = Mock()
                s.claim_sessions = Mock()
                for name in ('weather', 'gravity', 'credits'):
                    setattr(conn, name, Mock())
                for name in ('slots_gone', 'ground_ahead', 'update_far', 'maybe_prefetch',
                             'base_refresh', 'refresh_status'):
                    setattr(conn, name, Mock())
                conn.roads.close()
                conn.roads = Mock()
                conn.roads_pending = lambda: False
                conn.veg.close()
                conn.veg = Mock()
                try:
                    for x in (0., 40., 80.):
                        conn.on_pose(dict(type='pose', anchorId=anchor.id, x=x, y=0., vx=80., vy=0.))
                    self.assertEqual(conn.roads.on_pose.call_count, 3)
                    self.assertEqual(conn.veg.on_pose.call_count, 3)
                    self.assertTrue(im._warm_want, 'curved-road imagery was not queued')
                    self.assertEqual(conn.focus, (80., 0.))
                    im.warm(anchor.frame, np.empty((0, 2)), 100., 1.)
                finally:
                    im.close()
                    conn.bldfar.close()
                    conn.nav.close()
                    for name in ('tile_pool', 'hm_pool', 'base_pool', 'ahead_pool', 'landing_pool'):
                        getattr(s, name).shutdown(wait=True)
        asyncio.run(run())

    def test_transient_cache_read_lock_reuses_file_without_rebuilding(self):
        with tempfile.TemporaryDirectory() as root:
            md = mapdata.MapData(root, fetcher=netfetch.Fetcher(offline=True))
            path = str(Path(root, 'landcover.npz'))
            np.savez(path, provenance=np.array('null'), data=np.array([10, 30, 50]))
            load = np.load
            attempts = []
            def locked(*args, **kwargs):
                attempts.append(args[0])
                if len(attempts) <= 2:
                    raise PermissionError(13, 'Sharing violation', path)
                return load(*args, **kwargs)
            try:
                with patch.object(mapdata.np, 'load', side_effect=locked), patch.object(staging.time, 'sleep'), \
                     self.assertNoLogs('earthd.mapdata', 'WARNING'):
                    arrays = md._load(path)
                np.testing.assert_array_equal(arrays['data'], [10, 30, 50])
                self.assertEqual(len(attempts), 3)
            finally:
                md.close()

    def test_persistent_access_denial_does_not_claim_corruption_or_rebuild(self):
        with tempfile.TemporaryDirectory() as root:
            md = mapdata.MapData(root, fetcher=netfetch.Fetcher(offline=True))
            try:
                with patch.object(mapdata.np, 'load', side_effect=PermissionError(13, 'Access denied')), \
                     patch.object(staging.time, 'sleep'), patch.object(md, '_build') as build:
                    with self.assertRaises(PermissionError):
                        md.layer_arrays((14, 4319, 6097), 'landcover')
                    build.assert_not_called()
            finally:
                md.close()


if __name__ == '__main__':
    unittest.main()
