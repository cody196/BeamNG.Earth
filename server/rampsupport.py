"""Partition connected ramp ribbons at bridge abutments without changing deck profiles.

Supports are only the ramp's own bridges and its connected through carriageway. An
unrelated flyover cannot lift a ground ramp, cut its markings, or erase ground material.
"""
import numpy as np


def _coverage(points, support):
    p = np.asarray(points)[:, :2]
    line = support['line'][:, :2]
    ab = np.diff(line, axis=0)
    lengths = np.linalg.norm(ab, axis=1)
    t = np.clip(((p[:, None]-line[:-1])*ab).sum(2)/np.maximum(lengths**2, 1e-12), 0., 1.)
    distance = np.linalg.norm(p[:, None]-line[:-1]-t[..., None]*ab, axis=2).min(1)
    start = (p-line[0]) @ (ab[0]/max(lengths[0], 1e-9))
    end = (line[-1]-p) @ (ab[-1]/max(lengths[-1], 1e-9))
    return np.minimum(np.minimum(start, end), support['reach']-distance)


def runs(line, supports):
    """(support or None, ribbon), cut exactly at the supporting span's end planes.

    Carry every column (cross vectors/widths included) through the cut. Adjacent
    ground/deck pieces share the same point instead of leaving a sampling-sized gap.
    """
    import roads
    line = np.asarray(line)
    if len(line) < 2:
        return []
    if not supports:
        return [(None, line)]
    pieces = [(None, roads.densify(line, 2.))]
    lo, hi = line[:, :2].min(0), line[:, :2].max(0)
    for support in supports:
        p = support['line'][:, :2]
        if (p.max(0)+support['reach'] < lo).any() or (p.min(0)-support['reach'] > hi).any():
            continue
        result = []
        for owner, part in pieces:
            if owner is not None:
                result.append((owner, part))
                continue
            values = _coverage(part, support)
            inside = values >= -1e-6
            current = [part[0]]
            state = bool(inside[0])
            for k in range(len(part)-1):
                if inside[k] != inside[k+1]:
                    a, b = 0., 1.
                    for _ in range(20):
                        t = (a+b)/2
                        value = _coverage((part[k]+t*(part[k+1]-part[k]))[None], support)[0]
                        if (value >= 0) == inside[k]:
                            a = t
                        else:
                            b = t
                    cut = part[k]+((a+b)/2)*(part[k+1]-part[k])
                    current.append(cut)
                    if np.linalg.norm(current[-1][:2]-current[0][:2]) > 1e-5:
                        result.append((support if state else None, np.asarray(current)))
                    current = [cut]
                    state = bool(inside[k+1])
                current.append(part[k+1])
            if len(current) > 1 and np.linalg.norm(current[-1][:2]-current[0][:2]) > 1e-5:
                result.append((support if state else None, np.asarray(current)))
        pieces = result
    return pieces


def height(points, support, decks):
    """Sample the existing solved deck, retaining its longitudinal grade exactly."""
    import roads
    lines = [(roads._with_cross(p, {}), sp.width/2) for fid, sp, p, _ in decks if fid == support['fid']]
    if not lines:
        return None
    return roads._nearest_road(np.asarray(points), lines)[0][:, 2]
