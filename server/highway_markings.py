"""Physical US road-paint profiles from ROAD_IMPROVEMENT_NOTES.md (2026-10-23).

The gap is unpainted distance, not the complete repeat. Census state polygons are
bundled so driving never needs a state lookup from the network. Non-US roads keep
the upstream markings. Border cuts and dash phase are independent of tile cuts.
"""
from functools import lru_cache
import json
from pathlib import Path

import numpy as np

DATA = Path(__file__).with_name('highway_marking_states.geojson')
# (travel dash, travel width, travel gap, ramp dash, ramp width, ramp gap, solid width)
DEFAULT = (3.0, .35, 8.0, 1.2, .35, 2.8, .35)
PROFILES = {
    'MI': (4.5, .4, 11.5, 1.5, .35, 6.0, .4),
    'MN': (3.1, .3, 12.25, 0., 0., 0., .45),
    'WI': (5.15, .31, 10.25, 1.25, .3, 2.9, .32),
    'CA': (4.6, .35, 10.5, 2.3, .25, 4.9, .25),
}


@lru_cache(maxsize=1)
def _polygons():
    result = []
    data = json.loads(DATA.read_text(encoding='utf-8'))
    for feature in data['features']:
        state = feature['properties']['STUSAB']
        g = feature['geometry']
        polygons = [g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']
        for polygon in polygons:
            rings = [np.asarray(r, np.float64) for r in polygon]
            result.append((state, rings[0].min(0), rings[0].max(0), rings))
    return result


def states(lat, lon):
    """State abbreviation, or '' outside the 50 states / DC; holes and islands respected."""
    lat, lon = np.broadcast_arrays(lat, lon)
    x, y = lon.ravel(), lat.ravel()
    found = np.full(len(x), '', dtype='U2')
    for state, lo, hi, rings in _polygons():
        use = np.flatnonzero((found == '') & (x >= lo[0]) & (x <= hi[0]) & (y >= lo[1]) & (y <= hi[1]))
        if not len(use):
            continue
        px, py = x[use, None], y[use, None]
        inside = np.zeros(len(use), bool)
        for ring in rings:
            a, b = ring[:-1], ring[1:]
            relevant = (np.maximum(a[:, 1], b[:, 1]) >= py.min()) & (np.minimum(a[:, 1], b[:, 1]) <= py.max())
            a, b = a[relevant], b[relevant]
            dy = b[:, 1]-a[:, 1]
            intercept = a[:, 0]+(py-a[:, 1])*(b[:, 0]-a[:, 0])/np.where(dy == 0., 1., dy)
            inside ^= (((a[:, 1] > py) != (b[:, 1] > py)) & (px < intercept)).sum(1) % 2 != 0
        found[use[inside]] = state
    return found.reshape(lat.shape)


def apply(chunks, frame):
    """Dimension road paint, including ramps and fixed bridge paint, before mesh generation."""
    out = []
    for chunk in chunks:
        material = chunk['m']
        dashed = material.startswith('line_dashed')
        if chunk.get('keep_dimensions') or (not dashed and material not in ('line_white', 'line_yellow')) or len(chunk.get('n', ())) < 2:
            out.append(chunk)
            continue
        p = np.asarray(chunk['n'], np.float64)
        arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(p[:, :2], axis=0), axis=1))]
        if arc[-1] < 1e-6:
            continue
        at = np.linspace(0., arc[-1], max(2, int(np.ceil(arc[-1]/4.))+1))
        def state_at(distance):
            la, lo, _ = frame.enu_to_geodetic(np.interp(distance, arc, p[:, 0]), np.interp(distance, arc, p[:, 1]), 0.)
            return states(la, lo)
        flags = state_at(at)
        if not np.any(flags != ''):
            out.append(chunk)
            continue
        cuts = [0.]
        for k in np.flatnonzero(flags[1:] != flags[:-1]):
            a, b = at[k:k+2]
            for _ in range(10):
                mid = (a+b)/2
                if str(state_at(mid)) == flags[k]:
                    a = mid
                else:
                    b = mid
            cuts.append((a+b)/2)
        cuts.append(float(arc[-1]))
        for a, b in zip(cuts[:-1], cuts[1:]):
            samples = np.r_[a, arc[(arc > a) & (arc < b)], b]
            copy = dict(chunk, n=np.column_stack([np.interp(samples, arc, p[:, d]) for d in range(3)]).tolist())
            if chunk.get('cross'):
                cross = np.asarray(chunk['cross'])
                copy['cross'] = np.c_[np.interp(samples, arc, cross[:, 0]), np.interp(samples, arc, cross[:, 1])].tolist()
            if chunk.get('wn'):
                copy['wn'] = np.interp(samples, arc, chunk['wn']).tolist()
            copy['uv_start'] = chunk.get('uv_start', 0.) + a
            state = str(state_at((a+b)/2))
            if state:
                profile = PROFILES.get(state, DEFAULT)
                if dashed:
                    ramp = chunk.get('ramp_guidance') or chunk.get('ramp_lane')
                    dash, width, gap = profile[3:6] if ramp else profile[:3]
                    if dash == 0.:       # Minnesota ramp dots omitted; solid edges / terminal paint stay.
                        continue
                    copy.update(w=width, dash=dash, gap=gap, tl=dash+gap)
                else:
                    copy['w'] = profile[6]
                    if chunk.get('centre_pair'):
                        # Retain a visible gap between widened double centre lines.
                        import roadmesh
                        points = np.asarray(copy['n'])
                        normal = roadmesh._normals(points[:, :2])
                        points[:, :2] += normal * chunk['centre_pair'] * (profile[6]/2 + .06 - .12)
                        copy['n'] = points.tolist()
            out.append(copy)
    return out
