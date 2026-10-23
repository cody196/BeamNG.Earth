"""Generated tiles survive new sessions safely, with no repeated mesh/terrain work."""
from concurrent.futures import ThreadPoolExecutor, Future
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import cache
import blockworker
import earthd
import generatedcache as gc
import heightmap
import mapdata
import roads
from test_roads import LAT, LON, features
from test_roads import FRAME
from test_blockworker import FakeMapData, FakeDem


class GeneratedCacheTest(unittest.TestCase):
    def road(self, out, aid):
        names = roads.shape_files(aid, -1, 2)
        data = {"v": 1, "chunks": [], "colliders": {"deck": [[1, 2, 3, 4, 5, 6]]},
                "props": {"items": [[0, 1, 2, 3]], "groups": ["lamp"]}, "park": [[1, 2, 3, 4]]}
        for role, name in names.items():
            Path(out, name).write_bytes(b"mesh:"+role.encode())
            data[role] = {"shape": f"/temp/old/{name}", "pos": [-256, 512, 0]}
        path = Path(out, f"roads_{aid}_-1_2.json")
        path.write_text(json.dumps(data))
        return str(path), 12

    def test_road_bundle_rebinds_every_shape_without_changing_geometry_or_props(self):
        with tempfile.TemporaryDirectory() as root:
            a, b = Path(root, "a"), Path(root, "b")
            a.mkdir(); b.mkdir()
            store = gc.GeneratedCache(root, {"code": "test", "grading": True})
            key = (LAT, LON, 15, .03125, False, True, -1, 2)
            gc.save_roads(store, key, a, 7, -1, 2, self.road(a, 7))
            got = gc.load_roads(gc.GeneratedCache(root, {"grading": True, "code": "test"}),
                                key, b, "/temp/new", 42, -1, 2)
            self.assertEqual(got, ("/temp/new/roads_42_-1_2.json", 12))
            data = json.loads(Path(b, "roads_42_-1_2.json").read_text())
            self.assertNotIn("/temp/old", json.dumps(data))
            self.assertEqual(data["colliders"]["deck"], [[1, 2, 3, 4, 5, 6]])
            self.assertEqual(data["props"]["groups"], ["lamp"])
            for role, name in roads.shape_files(42, -1, 2).items():
                self.assertEqual(Path(b, name).read_bytes(), b"mesh:"+role.encode())
                self.assertEqual(data[role]["shape"], "/temp/new/"+name)

    def test_changed_settings_origin_height_quantum_and_code_miss(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "source")
            source.write_bytes(b"ok")
            key = [LAT, LON, .03125, 512]
            store = gc.GeneratedCache(root, {"code": "a", "grading": True})
            store.save("terrain", key, {}, {"height": source})
            for identity in ({"code": "b", "grading": True}, {"code": "a", "grading": False}):
                self.assertIsNone(gc.GeneratedCache(root, identity).load("terrain", key))
            for changed in ([LAT+.000001, LON, .03125, 512], [LAT, LON, .0625, 512], [LAT, LON, .03125, 1024]):
                self.assertIsNone(store.load("terrain", changed))

    def test_corrupt_or_interrupted_entry_is_a_miss(self):
        with tempfile.TemporaryDirectory() as root:
            store = gc.GeneratedCache(root, {})
            p = Path(store.path("roads", [1]))
            p.parent.mkdir(parents=True)
            p.write_bytes(b"half a zip file")
            self.assertIsNone(store.load("roads", [1]))
            self.assertEqual(store.stats["invalid"], 1)
            # An unfinished write is never opened as the committed cache entry.
            p.unlink()
            Path(str(p)+".123.tmp").write_bytes(b"unfinished")
            self.assertIsNone(store.load("roads", [1]))

    def test_bundle_checksum_rejects_modified_payload(self):
        import zipfile
        with tempfile.TemporaryDirectory() as root:
            store = gc.GeneratedCache(root, {})
            source = Path(root, "source")
            source.write_bytes(b"good")
            store.save("roads", [1], {}, {"road": source})
            p = store.path("roads", [1])
            with zipfile.ZipFile(p) as z:
                manifest = z.read("manifest.json")
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("manifest.json", manifest)
                z.writestr("road", b"changed")
            self.assertIsNone(store.load("roads", [1]))

    def test_fallback_cache_expires_when_optional_source_arrives(self):
        with tempfile.TemporaryDirectory() as root:
            store = gc.GeneratedCache(root, {})
            source = Path(root, "source")
            source.write_bytes(b"road without optional lots")
            missing = Path(root, "mapdata", "land_use.npz")
            store.save("roads", [1], {}, {"road": source}, [missing])
            self.assertIsNotNone(store.load("roads", [1]))
            missing.parent.mkdir()
            missing.write_bytes(b"arrived")
            self.assertIsNone(store.load("roads", [1]))

    def test_terrain_bundle_keeps_unmodified_physics_and_rebinds_all_material_masks(self):
        import surface
        with tempfile.TemporaryDirectory() as root:
            a, b = Path(root, "a"), Path(root, "b")
            a.mkdir(); b.mkdir()
            store = gc.GeneratedCache(root, {})
            Path(a, "old.png").write_bytes(b"height")
            Path(a, "old.ter").write_bytes(b"raw graded terrain")
            layers = surface.mask_names("old")
            for i, name in enumerate(layers):
                Path(a, name).write_bytes(f"mask{i}".encode())
            info = {"cx": 0., "cy": 0., "q": .03125, "ter": "old.ter", "layers": layers,
                    "stages": {"heights": 9.}, "base": "old_photo.png", "surfaceComplete": True}
            gc.save_terrain(store, [1], a, "old.png", info)
            Path(a, "old.ter").write_bytes(b"later photo-lawn edit")
            got = gc.load_terrain(store, [1], b, "fresh.png", "fresh_7.ter")
            self.assertEqual(Path(b, got["ter"]).read_bytes(), b"raw graded terrain")
            self.assertNotIn("base", got)
            for i, name in enumerate(got["layers"]):
                self.assertTrue(name.startswith("fresh"))
                self.assertEqual(Path(b, name).read_bytes(), f"mask{i}".encode())

    def test_deduplicates_concurrent_generation_and_releases_job_locks(self):
        with tempfile.TemporaryDirectory() as root:
            store = gc.GeneratedCache(root, {})
            source = Path(root, "source")
            source.write_bytes(b"geometry")
            builds = []
            def request():
                with store.job("roads", [1]):
                    got = store.load("roads", [1])
                    if got is None:
                        builds.append(1)
                        time.sleep(.03)
                        store.save("roads", [1], {}, {"road": source})
                    return store.load("roads", [1])
            with ThreadPoolExecutor(4) as pool:
                got = list(pool.map(lambda _: request(), range(4)))
            self.assertEqual(len(builds), 1)
            self.assertTrue(all(r[1]["road"] == b"geometry" for r in got))
            self.assertFalse(store._jobs)

    def test_generated_files_participate_in_the_cache_cap_and_clear(self):
        with tempfile.TemporaryDirectory() as root:
            disk = cache.Cache(root, start=False)
            source = Path(root, "source")
            source.write_bytes(b"geometry")
            store = gc.GeneratedCache(root, {}, disk)
            store.save("roads", [1], {}, {"road": source})
            p = store.path("roads", [1])
            self.assertEqual(disk._key(p).split("/")[0], "generated")
            self.assertTrue(disk._evictable(disk._key(p), 100))
            disk.close()
            # No live session uses the old entry in this new manager.
            later = cache.Cache(root, start=False)
            later.scan()
            later.clear()
            self.assertFalse(Path(p).exists())
            later.close()


class RoadReuseTest(unittest.TestCase):
    def test_real_mesh_reuse_skips_source_and_generation_in_both_worker_modes(self):
        class CompleteMapData(FakeMapData):
            @contextmanager
            def capture_complete(self):
                yield mapdata.SourceCapture()
        class WorkerPool:
            def submit(self, fn, *args):
                future = Future()
                try: future.set_result(fn(*args))
                except Exception as e: future.set_exception(e)
                return future
        for in_worker in (False, True):
            with self.subTest(worker=in_worker), tempfile.TemporaryDirectory() as root:
                f = features([[(-300.,100.), (0.,120.), (300.,100.)], [(120.,-100.), (120.,300.)]],
                             ["secondary", "residential"])
                md = CompleteMapData(f, roads.cells_of_tile(FRAME,0,0)[0])
                s = earthd.Server(str(Path(root,"user")), str(Path(root,"cache")), mapdata=md,
                                  grading=False, road_widths=False, imagery=None)
                s.dem = FakeDem()
                if in_worker: s.road_pool = WorkerPool()
                state = SimpleNamespace(md=md, dem=FakeDem(), widths=None, surface=None, airports=None,
                    sea=None, lock=threading.Lock(), bridges={}, anchor=lambda *args:(None,None))
                a = s.new_anchor(LAT,LON); a.q = heightmap.Q_DEFAULT; s.anchors[a.id] = a
                b = s.new_anchor(LAT,LON); b.q = a.q; s.anchors[b.id] = b
                with patch.object(blockworker,"_s",state), patch.object(s,"_build_roads_tile",wraps=s._build_roads_tile) as build:
                    first = s.build_roads_tile(a.id,0,0)
                    original = Path(s.out_dir,roads.shape_files(a.id,0,0)["road"]).read_bytes()
                    with patch.object(md,"cell",side_effect=AssertionError("cache hit read source data")):
                        second = s.build_roads_tile(b.id,0,0)
                self.assertEqual(build.call_count,1)
                self.assertEqual(s.generated.stats["writes"],1)
                self.assertEqual(first[1],second[1])
                self.assertEqual(Path(s.out_dir,roads.shape_files(b.id,0,0)["road"]).read_bytes(),original)


class SourceCompletenessTest(unittest.TestCase):
    def test_handled_source_errors_are_distinct_from_optional_misses(self):
        md = object.__new__(mapdata.MapData)
        md._capture, md._mem_lock, md._mem = threading.local(), threading.Lock(), {}
        md.pool = ThreadPoolExecutor(1)
        md.versions = lambda:{}
        md.layer_arrays = lambda *args: (_ for _ in ()).throw(OSError("temporary source failure"))
        try:
            with md.capture_complete() as capture:
                with self.assertRaises(OSError):
                    md.cell(roads.mapcells.cell_of(LAT,LON), layers=("roads",))
            self.assertTrue(capture.failed)
            self.assertFalse(capture[0])
        finally:
            md.pool.shutdown()

    def test_arriving_landcover_invalidates_in_memory_road_specs(self):
        with tempfile.TemporaryDirectory() as root:
            md = object.__new__(mapdata.MapData)
            md._capture, md._source_lock = threading.local(), threading.Lock()
            md._source_pending, md.geometry_epoch = set(), 0
            md.path = lambda key, layer: str(Path(root, layer))
            class Urban:
                def __init__(self): self.md = md
                def sample(self, la, lo):
                    return np.full(np.shape(la), self.md.has(None, "landcover"))
            urban = Urban()
            f = features([[(0., 0.), (200., 0.)]], ["residential"])
            self.assertFalse(roads.road_specs(f, urban.sample)[0].urban)
            Path(root, "landcover").write_bytes(b"urban data arrived")
            md.refresh_geometry_epoch()
            self.assertTrue(roads.road_specs(f, urban.sample)[0].urban)
            self.assertEqual(md.geometry_epoch, 1)

    def test_nonblocking_miss_and_nested_capture_are_thread_local(self):
        with tempfile.TemporaryDirectory() as root:
            md = object.__new__(mapdata.MapData)
            md._capture = threading.local()
            md.path = lambda key, layer: str(Path(root, layer))
            Path(root, "roads").write_bytes(b"cached")
            with md.capture_complete() as outer:
                with md.capture_complete() as inner:
                    self.assertFalse(md.has(None, "landcover"))
                self.assertFalse(inner[0])
            self.assertFalse(outer[0])
            with md.capture_complete() as clean:
                with ThreadPoolExecutor(1) as pool:
                    pool.submit(md.has, None, "landcover").result()
                self.assertTrue(md.has(None, "roads"))
            self.assertTrue(clean[0])


class TerrainReuseTest(unittest.TestCase):
    def test_failed_dem_fallback_is_never_persisted_even_with_optional_misses(self):
        s = SimpleNamespace(generated=object(), out_dir="unused", hm_name=lambda k:"unused.png",
                            _physics_key=lambda *args: (1,))
        info = {"_cacheComplete": True, "_sourceMissing": ["missing/landcover"], "_demComplete": False}
        with patch.object(gc, "save_terrain") as save:
            earthd.Server._save_physics(s, SimpleNamespace(id=1), 0., 0., info)
            save.assert_not_called()

    def test_new_request_borrows_idle_process_but_prefetch_never_takes_request_lane(self):
        with tempfile.TemporaryDirectory() as root:
            s = SimpleNamespace(out_dir=root, block_pools=[object(), object()], block_load=[1, 0],
                                block_lock=threading.Lock(),
                                _make_heightmap=lambda a, x, y, progress, lane, queued_at: lane)
            anchor = SimpleNamespace(id=1)
            got = earthd.Server.make_heightmap(s, anchor, 0., 0., None)
            self.assertEqual(got, earthd.LANE_PREFETCH)
            self.assertEqual(s.block_load, [1, 0])
            s.block_load = [0, 1]
            got = earthd.Server.make_heightmap(s, anchor, 0., 0., None, earthd.LANE_PREFETCH)
            self.assertEqual(got, earthd.LANE_PREFETCH)
            self.assertEqual(s.block_load, [0, 1])

    def test_new_session_uses_graded_block_without_reading_dem_or_regenerating(self):
        class FlatDem:
            def sample(self, la, lo, zoom, progress=None):
                return np.full(np.shape(la), 180.)
        class NoDem:
            def sample(self, *args, **kwargs):
                raise AssertionError("cached terrain must not be regenerated")
        with tempfile.TemporaryDirectory() as root:
            cache_dir = str(Path(root, "cache"))
            first = earthd.Server(str(Path(root, "user1")), cache_dir, near_visual="mesh", block=512)
            first.dem = FlatDem()
            a = first.new_anchor(LAT, LON)
            a.q = heightmap.Q_DEFAULT
            info = first.make_heightmap(a, 0., 0., None)
            original = Path(first.out_dir, info["ter"]).read_bytes()
            self.assertEqual(first.generated.stats["writes"], 1)
            second = earthd.Server(str(Path(root, "user2")), cache_dir, near_visual="mesh", block=512)
            second.dem = NoDem()
            second.new_anchor(0., 0.)  # different runtime ID, same geographic frame below
            b = second.new_anchor(LAT, LON)
            b.q = heightmap.Q_DEFAULT
            with patch.object(second, "_make_heightmap_here", side_effect=AssertionError("regenerated")):
                got = second.make_provisional(b, 0., 0., None)
            self.assertTrue(got.pop("_gradedCache"))
            self.assertEqual(Path(second.out_dir, got["ter"]).read_bytes(), original)
            self.assertNotEqual(got["ter"], info["ter"])
            for field in ("q", "zBase", "maxHeight", "groundZ"):
                self.assertEqual(got[field], info[field])


if __name__ == "__main__":
    unittest.main()
