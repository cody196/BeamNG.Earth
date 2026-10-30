"""Longitudinal paint dimensions from the project's ROAD_IMPROVEMENT_NOTES.md (metres).

The beta's native dash geometry consumes these dimensions before tile clipping.
"""
from collections import namedtuple

import numpy as np

Profile = namedtuple('Profile', 'travel ramp solid')
DEFAULT = Profile((3.0, 8.0, .35), (1.2, 2.8, .35), .35)
PROFILES = {
    'KY': Profile((3.5, 8.2, .3), None, .3),
    'MI': Profile((4.5, 11.5, .4), (1.5, 6.0, .35), .4),
    'MN': Profile((3.1, 12.25, .3), None, .45),
    'WI': Profile((5.15, 10.25, .31), (1.25, 2.9, .3), .32),
    'CA': Profile((4.6, 10.5, .35), (2.3, 4.9, .25), .25),
}


def profile(state=''):
    return PROFILES.get(state, DEFAULT)


def for_road(country=None, lon=None, state=''):
    """Project dimensions in the US; explicit other-country styles stay intact."""
    c = str(country or '').upper()
    return profile(state) if c == 'US' or (not c and (state or lon is not None and -170 <= lon <= -30)) else None


def specs(feats, values):
    """Select once per complete feature, shared by ground, bridges and tunnels."""
    import signstates
    selected = feats.__dict__.get('_marking_states')
    if selected is None:
        points = []
        for i in range(len(feats)):
            a = feats.coord_off[feats.ring_off[feats.part_off[i]]]
            b = feats.coord_off[feats.ring_off[feats.part_off[i+1]]]
            points.append(feats.lonlat[(a+b)//2] if b > a else [float('nan')]*2)
        ll = np.asarray(points, float).reshape(-1, 2)
        selected = feats.__dict__['_marking_states'] = signstates.states(ll[:, 1], ll[:, 0])
    return [sp._replace(state=str(state)) if sp is not None else None for sp, state in zip(values, selected)]
