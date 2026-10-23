"""Real worker-process cache coordination and crash recovery (including Windows)."""
from pathlib import Path
import multiprocessing
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cachelock


def build_layer(root, start, results):
    import numpy as np
    import mapdata
    import netfetch
    mapdata.MIRROR_MB = 0
    md = mapdata.MapData(root, fetcher=netfetch.Fetcher(offline=True))
    def build(*args):
        with open(Path(root, 'builds.txt'), 'a') as f:
            f.write('built\n')
        time.sleep(.3)  # Both processes see the initial miss while this one builds.
        return dict(provenance=np.array('null'), data=np.array([10, 30, 50]))
    md._build = build
    try:
        start.wait(5)
        arrays, hit = md.layer_arrays((14, 4319, 6097), 'landcover')
        results.put((arrays['data'].tolist(), hit))
    finally:
        md.close()


def hold_until_stopped(root, ready):
    with cachelock.hold(str(Path(root, 'tile.npz')), root):
        ready.set()
        time.sleep(30)


class CacheLockTest(unittest.TestCase):
    def test_two_worker_processes_build_one_cache_entry(self):
        ctx = multiprocessing.get_context('spawn')
        with tempfile.TemporaryDirectory() as root:
            start, results = ctx.Event(), ctx.Queue()
            jobs = [ctx.Process(target=build_layer, args=(root, start, results)) for _ in range(2)]
            try:
                for job in jobs: job.start()
                start.set()
                got = [results.get(timeout=15) for _ in jobs]
                for job in jobs:
                    job.join(5)
                    self.assertEqual(job.exitcode, 0)
                self.assertEqual(Path(root, 'builds.txt').read_text().splitlines(), ['built'])
                self.assertEqual(sorted(hit for _, hit in got), [False, True])
                self.assertTrue(all(values == [10, 30, 50] for values, _ in got))
            finally:
                for job in jobs:
                    if job.is_alive(): job.terminate()
                    job.join(5)
                results.close()
                results.join_thread()

    def test_busy_timeout_and_crashed_builder_release(self):
        ctx = multiprocessing.get_context('spawn')
        with tempfile.TemporaryDirectory() as root:
            ready = ctx.Event()
            job = ctx.Process(target=hold_until_stopped, args=(root, ready))
            job.start()
            try:
                self.assertTrue(ready.wait(5))
                with self.assertRaises(TimeoutError):
                    with cachelock.hold(str(Path(root, 'tile.npz')), root, timeout=.05):
                        self.fail('two processes entered the same cache miss')
                with cachelock.hold(str(Path(root, 'unrelated.npz')), root, timeout=.05):
                    pass
            finally:
                job.terminate()
                job.join(5)
            with cachelock.hold(str(Path(root, 'tile.npz')), root, timeout=.5):
                pass


if __name__ == '__main__':
    unittest.main()
