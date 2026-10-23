"""Source-based road neighbourhoods, independent of the cell that asks for a curve.

Road features are whole polylines repeated in each cell they touch. Fitting those copies
against their own cell's neighbours gives different curves at a cell boundary. Use the
stable source-end neighbourhoods instead, also retaining the full approach to a ramp.
The bounded cache is shared by rendering, grading, surface masks and navigation.
"""
from collections import OrderedDict
from concurrent.futures import Future
import json
import threading

import numpy as np

import mapcells
import mapgeom


MARGIN_M = 320.                 # full auxiliary lane and taper, before clipping
MAX_CONTEXTS = 64               # one interchange can exceed 12; keep the byte cap below
MAX_BYTES = 64 * 1024 * 1024


def merge(cells):
    """Whole source features and their rules, once by ID, in deterministic cell order."""
    rows = {}
    lane_sections = {}
    for feats in cells:
        if feats is not None:
            for i, fid in enumerate(feats.ids):
                rows.setdefault(str(fid), (feats, i))
                col = feats.attrs.get('osm_lane_sections')
                if col is not None:
                    for section in json.loads(str(col[i]) or '[]'):
                        key = (section['start'], section['end'], section.get('way', 0))
                        lane_sections.setdefault(str(fid), {})[key] = section
    ordered = [rows[fid] for fid in sorted(rows)]
    out = mapgeom.build('roads', np.array(sorted(rows), dtype=str),
                        [(int(f.kind[i]), f.parts(i)) for f, i in ordered])
    for name in sorted({k for f, _ in ordered for k in f.attrs}):
        dtype = np.result_type(*[f.attrs[name].dtype for f, _ in ordered if name in f.attrs])
        missing = '' if dtype.kind in 'US' else (np.nan if dtype.kind in 'fc' else 0)
        out.attrs[name] = np.array([f.attrs[name][i] if name in f.attrs else missing
                                    for f, i in ordered], dtype=dtype)
    if lane_sections:
        out.attrs['osm_lane_sections'] = mapgeom.text_column([
            json.dumps([v for _, v in sorted(lane_sections.get(fid, {}).items())], separators=(',', ':'))
            for fid in sorted(rows)])
        # A neighboring cell may hold tags of a different part of the same full feature.
        if 'osm_lanes' in out.attrs:
            for i, fid in enumerate(sorted(rows)):
                if not np.isfinite(out.attrs['osm_lanes'][i]) and lane_sections.get(fid):
                    out.attrs['osm_lanes'][i] = max(lane_sections[fid].values(), key=lambda s:s['end']-s['start'])['lanes']
    for name in sorted({k for f, _ in ordered for k in f.rules}):
        fi, values, starts, ends = [], [], [], []
        dtype = np.result_type(*[f.rules[name].value.dtype for f, _ in ordered if name in f.rules])
        for j, (f, i) in enumerate(ordered):
            table = f.rules.get(name)
            if table is None:
                continue
            r = table.rows(i)
            fi.extend([j] * len(r))
            values.extend(table.value[r])
            starts.extend(table.start[r])
            ends.extend(table.end[r])
        out.rules[name] = mapgeom.RuleTable(np.array(fi, np.int32), np.array(values, dtype=dtype),
                                          np.array(starts, np.float32), np.array(ends, np.float32))
    return out


class Context:
    def __init__(self, cell):
        self.cell = cell
        self.cache = OrderedDict()
        self.bytes = 0
        self.lock = threading.RLock()
        self.pending = {}

    @staticmethod
    def points(feats, i):
        """Topology context for one source road, without fetching its entire corridor.

        A highway feature can span tens of kilometres. Its interior shape and pinned
        connectors already come with the source geometry; only the ends need other
        features for shared tangents and lane transitions. Short roads and ramps keep
        their full neighbourhood (including the approach to an auxiliary lane).
        """
        import roads
        rings = [r[:, :2] for part in feats.parts(i) for r in part if len(r)]
        if not rings:
            return np.empty((0, 2))
        if not roads.is_link(feats, i) and roads._feature_length_m(feats, i) > 2*MARGIN_M:
            return np.concatenate([r[[0, -1]] for r in rings])
        return np.concatenate(rings)

    @staticmethod
    def keys(points):
        points = np.asarray(points, float)
        if not len(points):
            return ()
        pad = MARGIN_M / 110540.
        lon_pad = pad / max(.01, float(np.cos(np.radians(points[:, 1])).min()))
        return tuple(mapcells.cells_near_points(points[:, 1], points[:, 0], pad, lon_pad))

    def required(self, feats):
        """Cells needed before a nonblocking terrain painter can use these highway curves."""
        import roads
        keys = set()
        for i in range(len(feats)):
            cls = str(feats.attrs.get('class', ['unknown'] * len(feats))[i])
            if cls not in ('motorway', 'trunk') and not roads.is_link(feats, i):
                continue
            keys.update(self.keys(self.points(feats, i)))
        return sorted(keys, key=str)

    def feature(self, feats, i):
        """(complete neighbourhood, source row) for this feature, regardless of caller/load order.

        Only topology needs context: a long highway does not fetch every cell along
        its route. Failed reads propagate for the caller to retry; incomplete
        neighbourhoods must not become permanent, differently fitted roads.
        """
        points = self.points(feats, i)
        if not len(points):
            source = merge([feats])
            return source, source.index(str(feats.ids[i]))
        source = self.around(points)
        row = source.index(str(feats.ids[i]))
        if row < 0:
            raise ValueError(f'road context is missing source feature {feats.ids[i]}')
        return source, row

    def around(self, points):
        """One stable neighbourhood for a whole source line or an OSM exit approach."""
        points = np.asarray(points, float)
        if not len(points):
            return mapgeom.empty('roads')
        keys = self.keys(points)
        with self.lock:
            got = self.cache.get(keys)
            if got is not None:
                self.cache.move_to_end(keys)
                return got[0]
            pending = self.pending.get(keys)
            owner = pending is None
            if owner:
                pending = self.pending[keys] = Future()
        if not owner:
            return pending.result()
        try:
            # Network/cache reads must not hold the global lock: an unrelated
            # scenery worker may only need a different, already cached context.
            context = merge([self.cell(key) for key in keys])
            size = 3 * sum(a.nbytes for a in context.to_arrays('').values())
            with self.lock:
                self.cache[keys] = context, size
                self.bytes += size
                while (len(self.cache) > MAX_CONTEXTS or self.bytes > MAX_BYTES) and len(self.cache) > 1:
                    _, (_, old_size) = self.cache.popitem(last=False)
                    self.bytes -= old_size
            pending.set_result(context)
            return context
        except BaseException as error:
            pending.set_exception(error)
            raise
        finally:
            with self.lock:
                self.pending.pop(keys, None)
