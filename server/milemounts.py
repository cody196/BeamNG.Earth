"""Bundled fractional mile stations, mounted on the beta's own concrete medians.

The old marker inventory is retained without replacing 1.7.2's barrier rules,
geometry or collision. Where there is no concrete wall, whole-mile shoulder
markers remain available and fractional markers are omitted.
"""
from functools import lru_cache
import json
from pathlib import Path

import numpy as np

import exitsigns
import medians


@lru_cache(maxsize=1)
def station_sets():
    data = json.loads(Path(__file__).with_name('ky_interstate_medians.json').read_text(encoding='utf-8'))
    return [('KY', np.asarray(data['stations'], float).reshape(-1, 6)),
            ('IN', np.asarray(data.get('indiana_stations', []), float).reshape(-1, 6))]


def mount(frame, obj, pavements, elev):
    """Centre/top of a concrete module computed by the current road generator."""
    q = exitsigns._xy(frame, [[obj['lon'], obj['lat']]])[0]
    box = (q[0]-100., q[1]-100., q[0]+100., q[1]+100.)
    rows = [(fid, sp.road_spec, line, 0.) for fid, sp, line, _ in pavements
            if getattr(sp, 'road_spec', None) is not None]
    modules = medians.modules(rows, box, country='US')
    if not len(modules):
        return None
    modules = modules[(modules[:, 0] == medians.JERSEY) & (modules[:, 1] == 0)]
    if not len(modules):
        return None
    a, b = modules[:, 2:4], modules[:, 4:6]
    d = b-a
    lengths = np.linalg.norm(d, axis=1)
    t = np.clip(((q-a)*d).sum(1)/np.maximum(lengths**2, 1e-12), 0., 1.)
    points = a+d*t[:, None]
    distances = np.linalg.norm(points-q, axis=1)
    axis = np.asarray(obj['mile_marker']['axis'], float)
    tangents = d/np.maximum(lengths[:, None], 1e-12)
    valid = ((distances < 80.) & (np.abs(tangents@axis) > .8) &
             (np.abs(((points-q)*tangents).sum(1)) < 1.5))
    if not valid.any():
        return None
    k = int(np.argmin(np.where(valid, distances, np.inf)))
    travel = tangents[k] if tangents[k]@axis > 0 else -tangents[k]
    # The stock Jersey model used by medians.tile_rows is 0.88 m tall.
    z = exitsigns._ground_z(frame, elev, points[k]) + .88
    return np.r_[points[k], z], travel
