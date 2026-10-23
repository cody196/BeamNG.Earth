"""Reusable local road meshes and graded physics blocks.

Entries are bundles, committed atomically, with a manifest and checksummed files. They
contain no session paths: callers bind the files to a new session on a hit. Coordinates
remain in the exact ENU frame in the key; a different origin must never reuse them.
The ordinary download-cache cap and Clear cache also manage these bundles.
"""
from contextlib import contextmanager
import hashlib
import io
import json
import logging
import os
import threading
import zipfile

import cache
import staging

log = logging.getLogger("earthd.generatedcache")
VERSION = 1
MAX_BYTES = 128 << 20
MAX_FILES = 32


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


class GeneratedCache:
    def __init__(self, root, identity, disk=None):
        self.cache_dir = os.path.abspath(root)
        self.root = os.path.join(root, "generated", f"v{VERSION}", digest(identity)[:24])
        self.disk = disk or cache.NONE
        self.stats = {"hits": 0, "misses": 0, "writes": 0, "invalid": 0}
        self._lock = threading.Lock()
        self._jobs = {}

    def path(self, kind, key):
        if kind not in ("roads", "terrain"):
            raise ValueError("unknown generated tile kind")
        return os.path.join(self.root, kind, digest(key) + ".zip")

    @contextmanager
    def job(self, kind, key):
        """Share a build between connections; discard locks once nobody needs them."""
        name = self.path(kind, key)
        with self._lock:
            entry = self._jobs.setdefault(name, [threading.Lock(), 0])
            entry[1] += 1
        try:
            with entry[0]:
                yield
        finally:
            with self._lock:
                entry[1] -= 1
                if not entry[1]:
                    del self._jobs[name]

    def load(self, kind, key):
        path = self.path(kind, key)
        def read():
            with open(path, "rb") as f:
                return f.read(MAX_BYTES + 1)
        try:
            data = staging.retry_read(read)
            if len(data) > MAX_BYTES:
                raise ValueError("oversized generated tile")
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                entries = z.infolist()
                if len(entries) > MAX_FILES + 1 or sum(e.file_size for e in entries) > MAX_BYTES:
                    raise ValueError("oversized generated contents")
                manifest = json.loads(z.read("manifest.json"))
                if manifest["v"] != VERSION or manifest["key"] != digest(key):
                    raise ValueError("generated tile identity mismatch")
                for relative in manifest.get("missing", ()):
                    candidate = os.path.abspath(os.path.join(self.cache_dir, relative))
                    if os.path.commonpath((candidate, self.cache_dir)) != self.cache_dir:
                        raise ValueError("invalid generated source dependency")
                    if os.path.exists(candidate):
                        # An urban/lot fallback is useful while data is unavailable,
                        # but must be regenerated once that optional layer arrives.
                        self.stats["misses"] += 1
                        return None
                files = {}
                for name, checksum in manifest["files"].items():
                    # Never extract archive paths into the filesystem.
                    if not name.isidentifier():
                        raise ValueError("invalid generated file role")
                    b = z.read(name)
                    if hashlib.sha256(b).hexdigest() != checksum:
                        raise ValueError("generated tile checksum mismatch")
                    files[name] = b
            self.disk.used(path, len(data))
            self.stats["hits"] += 1
            return manifest["meta"], files
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, EOFError) as e:
            self.stats["invalid"] += 1
            log.debug("generated tile ignored (%s): %s", kind, e)
        self.stats["misses"] += 1
        return None

    def save(self, kind, key, meta, files, missing=()):
        """files maps logical roles to source filenames. Cache failures never lose a tile."""
        path, tmp = self.path(kind, key), None
        try:
            if len(files) > MAX_FILES or any(not n.isidentifier() for n in files):
                raise ValueError("invalid generated file roles")
            contents = {}
            for name, source in files.items():
                with open(source, "rb") as f:
                    contents[name] = f.read(MAX_BYTES + 1)
                if sum(map(len, contents.values())) > MAX_BYTES:
                    return
            missing = sorted(os.path.relpath(p, self.cache_dir) for p in missing)
            manifest = {"v": VERSION, "key": digest(key), "meta": meta, "missing": missing,
                        "files": {n: hashlib.sha256(b).hexdigest() for n, b in contents.items()}}
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
            # Meshes and PNGs are already compressed. Avoid spending a core zipping them again.
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as z:
                z.writestr("manifest.json", json.dumps(manifest, separators=(",", ":"), allow_nan=False))
                for name, b in contents.items():
                    z.writestr(name, b)
            staging.replace_cached(tmp, path)
            self.disk.wrote(path)
            self.stats["writes"] += 1
        except (OSError, ValueError, TypeError) as e:
            log.debug("generated tile not saved (%s): %s", kind, e)
        finally:
            if tmp is not None:
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def write_files(out_dir, files, names):
    """Publish validated bytes at caller-owned session names, atomically per file."""
    if set(files) != set(names):
        raise ValueError("generated tile files do not match metadata")
    for role, name in names.items():
        if os.path.basename(name) != name:
            raise ValueError("invalid generated session filename")
        path = os.path.join(out_dir, name)
        tmp = staging.tmp_for(path)
        with open(tmp, "wb") as f:
            f.write(files[role])
        staging.replace(tmp, path)


def save_roads(store, key, out_dir, aid, tx, ty, result, missing=()):
    import roads
    name = f"roads_{aid}_{tx}_{ty}.json"
    try:
        with open(os.path.join(out_dir, name)) as f:
            data = json.load(f)
        files = {}
        for role, shape in roads.shape_files(aid, tx, ty).items():
            if role in data:
                files[role] = os.path.join(out_dir, shape)
                data[role]["shape"] = role
        store.save("roads", key, {"data": data, "n": result[1]}, files, missing)
    except (OSError, ValueError, KeyError, TypeError) as e:
        log.debug("road geometry not cached: %s", e)


def load_roads(store, key, out_dir, vfs_dir, aid, tx, ty):
    import roads
    got = store.load("roads", key)
    if got is None:
        return None
    try:
        meta, files = got
        data = meta["data"]
        names = roads.shape_files(aid, tx, ty)
        if set(files) != {role for role in names if role in data}:
            raise ValueError("road manifest is incomplete")
        names = {role: names[role] for role in files}
        write_files(out_dir, files, names)
        for role, name in names.items():
            data[role]["shape"] = f"{vfs_dir}/{name}"
        name = f"roads_{aid}_{tx}_{ty}.json"
        path = os.path.join(out_dir, name)
        tmp = staging.tmp_for(path)
        with open(tmp, "w") as f:
            f.write(json.dumps(data, separators=(",", ":")))
        staging.replace(tmp, path)
        return f"{vfs_dir}/{name}", int(meta["n"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        log.debug("cached road geometry not restored: %s", e)
        return None


def save_terrain(store, key, out_dir, hm_name, info, missing=()):
    files = {"height": os.path.join(out_dir, hm_name)}
    if info.get("ter"):
        files["terrain"] = os.path.join(out_dir, info["ter"])
    for i, name in enumerate(info.get("layers", ())):
        files[f"layer{i}"] = os.path.join(out_dir, name)
    meta = {k: v for k, v in info.items() if k not in ("ter", "layers", "base", "seconds", "zoom", "stages")
            and not k.startswith("_")}
    store.save("terrain", key, meta, files, missing)


def load_terrain(store, key, out_dir, hm_name, ter_name):
    import surface
    got = store.load("terrain", key)
    if got is None:
        return None
    try:
        info, files = got
        names = {"height": hm_name, "terrain": ter_name}
        if "terrain" not in files:
            names.pop("terrain")
        if "layer0" in files:
            info["layers"] = surface.mask_names(hm_name[:-4])
            names.update({f"layer{i}": name for i, name in enumerate(info["layers"])})
        write_files(out_dir, files, names)
        if "terrain" in files:
            info["ter"] = ter_name
        info["stages"] = {"cacheHit": 1.0}
        return info
    except (OSError, ValueError, KeyError, TypeError) as e:
        log.debug("cached terrain not restored: %s", e)
        return None
