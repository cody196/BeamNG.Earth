"""Coordinate cache misses across the terrain, road and scenery worker processes.

Cached reads never take this lock. Only a builder takes it, then checks the cache
again. OS-owned locks disappear when a worker crashes, without stale lock cleanup.
"""
from contextlib import contextmanager
import hashlib
import os
import time

TIMEOUT_S = 120.

if os.name == 'nt':
    import ctypes
    from ctypes import wintypes
    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    _kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel.CreateMutexW.restype = wintypes.HANDLE
    _kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel.WaitForSingleObject.restype = wintypes.DWORD
    _kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    _kernel.ReleaseMutex.restype = wintypes.BOOL
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL


@contextmanager
def hold(path, cache_dir, timeout=TIMEOUT_S):
    name = hashlib.sha256(os.path.normcase(os.path.realpath(path)).encode()).hexdigest()
    if os.name == 'nt':
        handle = _kernel.CreateMutexW(None, False, 'Local\\BeamNGEarth-cache-'+name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        acquired = False
        try:
            result = _kernel.WaitForSingleObject(handle, max(0, int(timeout*1000)))
            # An abandoned mutex is ours. The caller re-reads/validates the atomic
            # cache file before using it, just as for an ordinary cache miss.
            if result not in (0, 0x80):
                if result == 0x102:
                    raise TimeoutError('cache builder still busy: '+str(path))
                raise ctypes.WinError(ctypes.get_last_error())
            acquired = True
            yield
        finally:
            if acquired:
                _kernel.ReleaseMutex(handle)
            _kernel.CloseHandle(handle)
    else:
        import fcntl
        # Bounded number of tiny lock files, outside the evictable cache trees.
        # Never unlink an active lock: another process could then lock a new inode.
        folder = os.path.join(cache_dir, 'locks', 'mapdata')
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name[:2]+'.lock'), 'a+b') as handle:
            deadline = time.monotonic()+timeout
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('cache builder still busy: '+str(path))
                    time.sleep(.02)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
