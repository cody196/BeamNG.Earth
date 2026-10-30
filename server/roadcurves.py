"""Bounded bends with continuous tangents and curvature for every road consumer.

Prepare decoded road cells, never the downloaded arrays. Junctions, endpoints,
and linear-rule boundaries stay fixed. Remap rule stations onto the new arc so
bridge spans, speed limits and connectors still refer to the same locations.
"""
from dataclasses import replace
from functools import lru_cache
import numpy as np
import mapgeom

STEP = 1.0
MAX_DEVIATION = 1.5


@lru_cache(maxsize=256)
def _basis(count):
    """Shared quintic samples; the sample count is bounded by the bend's trim/angle."""
    t = np.linspace(0, 1, count + 1)
    weights = np.array([(1-t)**5, 5*t*(1-t)**4, 10*t*t*(1-t)**3,
                        10*t**3*(1-t)**2, 5*t**4*(1-t), t**5]).T
    t.flags.writeable = weights.flags.writeable = False
    return t, weights


def rounded(points, pins=()):
    """(points, original stations, new stations); coordinates are local metres."""
    p = np.asarray(points, float)
    s = np.r_[0., np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    if len(p) < 3 or s[-1] < .01:
        return p.copy(), s, s.copy()
    pins = np.asarray(pins, float)
    pins = np.unique(np.r_[0., np.clip(pins[np.isfinite(pins)], 0, s[-1]), s[-1]])
    knots = np.unique(np.r_[s, pins])
    q = np.column_stack([np.interp(knots, s, p[:, d]) for d in range(p.shape[1])])
    # Classify every corner in one array pass. Per-point numpy calls and a scan
    # of every pin at every corner dominated cold road-cell preparation.
    delta = np.diff(q, axis=0)
    length = np.linalg.norm(delta, axis=1)
    unit = delta / np.maximum(length, 1e-12)[:, None]
    angle = np.arccos(np.clip(np.einsum('ij,ij->i', unit[:-1], unit[1:]), -1., 1.))
    at = np.searchsorted(pins, knots[1:-1])
    gap = np.minimum(np.abs(pins[np.minimum(at, len(pins)-1)] - knots[1:-1]),
                     np.abs(pins[np.maximum(at-1, 0)] - knots[1:-1]))
    bends = np.flatnonzero((np.minimum(length[:-1], length[1:]) >= .01) & (gap >= .01)
                          & (angle >= np.radians(.05)) & (angle <= np.radians(100)))
    trim = np.minimum(np.minimum(.49*length[bends], .49*length[bends+1]),
                      np.minimum(MAX_DEVIATION/(.375*np.maximum(np.sin(angle[bends]/2), 1e-6)), 120.))
    counts = np.maximum(8, np.maximum(np.ceil(2*trim/STEP),
                                     np.ceil(angle[bends]/np.radians(.5)))).astype(np.int64)
    sizes = np.ones(len(q), np.int64)
    sizes[bends+1] = counts+1
    offsets = np.r_[0, np.cumsum(sizes)]
    result = np.empty((offsets[-1], p.shape[1]), float)
    stations = np.empty(offsets[-1], float)
    result[offsets[:-1]], stations[offsets[:-1]] = q, knots
    # Equally spaced collinear endpoint controls retain zero end curvature and
    # the same 1.5 m displacement bound. Batch equal-sized curves; cap temporary
    # arrays for long features without reducing their sampling resolution.
    for count in np.unique(counts):
        group = np.flatnonzero(counts == count)
        t, weights = _basis(int(count))
        for first in range(0, len(group), 256):
            take = group[first:first+256]
            i, tr = bends[take]+1, trim[take, None]
            u, v = unit[i-1], unit[i]
            start, end = q[i]-u*tr, q[i]+v*tr
            controls = np.stack([start, start+.4*tr*u, start+.8*tr*u,
                                 end-.8*tr*v, end-.4*tr*v, end], axis=1)
            dst = offsets[i, None] + np.arange(count+1)
            result[dst] = weights @ controls
            stations[dst] = knots[i, None]-tr+2*tr*t
    keep = np.r_[True, np.linalg.norm(np.diff(result, axis=0), axis=1) > 1e-8]
    result, stations = result[keep], stations[keep]
    return result, stations, np.r_[0., np.cumsum(np.linalg.norm(np.diff(result, axis=0), axis=1))]


def prepare(feats):
    """A derived Features table. Safe to call twice; all non-road data untouched."""
    if feats.layer != 'roads' or getattr(feats, '_curved', False) or not len(feats.lonlat):
        return feats
    coords, offsets, remaps = [], [0], {}
    subtypes, classes = feats.attrs.get('subtype'), feats.attrs.get('class')
    for i in range(len(feats)):
        first = int(feats.ring_off[feats.part_off[i]])
        last = int(feats.ring_off[feats.part_off[i+1]])
        for r in range(first, last):
            ll = feats.lonlat[feats.coord_off[r]:feats.coord_off[r+1]]
            # Multi-part rule fractions have ambiguous part ownership: retain them.
            if (last-first != 1 or len(ll) < 3 or feats.kind[i] != mapgeom.LINE
                    or (subtypes is not None and str(subtypes[i]) != 'road')
                    or (classes is not None and str(classes[i]) == 'raceway')):
                coords.append(ll); offsets.append(offsets[-1]+len(ll)); continue
            scale = np.array([111320.*np.cos(np.radians(ll[:, 1].mean())), 110574.])
            p = (ll-ll[0])*scale
            s = np.r_[0., np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
            # Source connector/range rules accompany the complete feature in
            # every cell. Do not derive pins from whichever neighbours happen
            # to be loaded: that would give duplicate features different curves.
            pins = []
            for table in feats.rules.values():
                rows = table.rows(i)
                pins.extend(table.start[rows]*s[-1]); pins.extend(table.end[rows]*s[-1])
            q, old, new = rounded(p, pins)
            coords.append(q/scale+ll[0]); offsets.append(offsets[-1]+len(q))
            if s[-1] > .01 and new[-1] > .01:
                remaps[i] = old/s[-1], new/new[-1]
    rules = {}
    for name, table in feats.rules.items():
        start, end = table.start.copy(), table.end.copy()
        for i, (old, new) in remaps.items():
            rows = table.rows(i)
            start[rows] = np.interp(start[rows], old, new)
            end[rows] = np.interp(end[rows], old, new)
        rules[name] = mapgeom.RuleTable(table.feature, table.value, start, end)
    out = replace(feats, lonlat=np.concatenate(coords), coord_off=np.asarray(offsets, np.int64),
                  en=None, attrs=dict(feats.attrs), rules=rules)
    out._curved = True
    return out
