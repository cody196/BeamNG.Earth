"""Resolve lane counts once, before ground, bridge, tunnel and AI specs diverge.

Priority: explicit OSM way tag, unambiguous matching current OSM geometry, then
agreement along a connected through road. Never borrow lanes from a ramp,
opposing carriageway or crossing bridge. lane_source records the evidence.
"""
import numpy as np


def count(value):
    try:
        n = float(value)
        return int(n) if np.isfinite(n) and n.is_integer() and 1 <= n <= 32 else None
    except (TypeError, ValueError):
        return None


def _rule(feats, name, i):
    table = feats.rules.get(name)
    rows = table.rows(i) if table is not None else ()
    return table.value[rows[0]] if len(rows) else None


def _project(line, points):
    delta = np.diff(line, axis=0)
    length = np.maximum(np.linalg.norm(delta, axis=1), 1e-9)
    t = np.clip(((points[:, None]-line[None, :-1])*delta).sum(2)/length**2, 0., 1.)
    q = line[None, :-1] + t[:, :, None]*delta
    dist = np.linalg.norm(points[:, None]-q, axis=2)
    k = dist.argmin(1)
    return dist[np.arange(len(points)), k], delta[k]/length[k, None]


def resolve(feats, tags, way_ids):
    n = len(feats)
    raw = feats.attrs.get('osm_lanes', np.full(n, np.nan))
    counts = np.array([count(v) or np.nan for v in raw])
    sources = ['osm-way' if np.isfinite(v) else '' for v in counts]
    matched = np.array([w or 0 for w in way_ids], dtype=np.int64)
    classes = feats.attrs.get('class', np.full(n, ''))
    origin = feats.lonlat.mean(0) if len(feats.lonlat) else np.zeros(2)
    scale = np.array([111320.*np.cos(np.radians(origin[1])), 110574.])
    local = lambda p: (np.asarray(p)-origin)*scale
    lines, dirs, links = [], [], []
    for i in range(n):
        parts = feats.parts(i)
        line = local(parts[0][0]) if parts and parts[0] else np.empty((0, 2))
        if len(line):
            line = line[np.r_[True, np.linalg.norm(np.diff(line, axis=0), axis=1) > .01]]
        lines.append(line)
        d = _rule(feats, 'oneway', i)
        dirs.append(0 if d is None else -1 if float(d) < 0 else 1)
        links.append(_rule(feats, 'subclass', i) == 'link' or
                     str(feats.attrs.get('subclass', ['']*n)[i]) == 'link')

    candidates = []
    for wid, tag in tags.items():
        p = tag.get('_coords')
        lanes = count(tag.get('lanes'))
        if lanes is None or p is None or len(p) < 2:
            continue
        p = local(p)
        highway = tag.get('_highway', '')
        candidates.append((wid, lanes, highway.removesuffix('_link'), highway.endswith('_link'),
                           tag.get('osm_oneway', ''), p, p.min(0)-6., p.max(0)+6.))
    for i, line in enumerate(lines):
        if np.isfinite(counts[i]) or len(line) < 2:
            continue
        s = np.r_[0., np.cumsum(np.linalg.norm(np.diff(line, axis=0), axis=1))]
        samples = np.column_stack([np.interp(np.linspace(0., s[-1], 9), s, line[:, d]) for d in (0, 1)])
        _, tangent = _project(line, samples)
        matches = []
        for wid, lanes, cls, link, oneway, p, lo, hi in candidates:
            if cls != classes[i] or link != links[i] or np.any(samples < lo) or np.any(samples > hi):
                continue
            distance, heading = _project(p, samples)
            alignment = (tangent*heading).sum(1)
            od = -1 if oneway == '-1' else 1 if oneway in ('yes', '1', 'true') else 0
            if dirs[i] and od:
                alignment *= dirs[i]*od
            else:
                alignment = np.abs(alignment)
            if distance.max() <= 6. and np.mean(distance) <= 3. and alignment.min() >= .9:
                matches.append((float(np.mean(distance)), wid, lanes))
        matches.sort()
        if matches and not any(m[2] != matches[0][2] and m[0] < matches[0][0]+1. for m in matches[1:]):
            _, matched[i], counts[i] = matches[0]
            sources[i] = 'osm-geometry'

    # Connect only unbranched, aligned continuations. Different explicit counts
    # at opposite ends are a real/ambiguous lane transition, not a majority vote.
    endpoints, buckets = [], {}
    for i, line in enumerate(lines):
        if len(line) < 2 or links[i] or classes[i] not in {'motorway', 'trunk', 'primary', 'secondary', 'tertiary'}:
            continue
        for end, other in ((0, 1), (-1, -2)):
            tangent = line[other]-line[end]
            tangent /= max(np.linalg.norm(tangent), 1e-9)
            k = tuple(np.floor(line[end]).astype(int))
            e = len(endpoints)
            connectors = feats.rules.get('connectors')
            ids = frozenset(str(connectors.value[r]) for r in connectors.rows(i)
                            if abs(float(connectors.start[r])-(1. if end == -1 else 0.)) < .001) if connectors else frozenset()
            endpoints.append((i, line[end], tangent, dirs[i]*(1 if end == -1 else -1), ids))
            buckets.setdefault(k, []).append(e)
    choices = []
    for e, (i, p, tangent, flow, ids) in enumerate(endpoints):
        k = np.floor(p).astype(int)
        near = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in buckets.get((k[0]+dx, k[1]+dy), ()):
                    f, q, heading, flow2, ids2 = endpoints[j]
                    if ids and ids2 and ids.isdisjoint(ids2):
                        continue
                    if f != i and classes[f] == classes[i] and bool(dirs[f]) == bool(dirs[i]) and (
                            np.linalg.norm(p-q) <= .75 and tangent @ heading < -.9 and flow == -flow2):
                        near.append(j)
        choices.append(near)
    adj = [set() for _ in range(n)]
    for e, near in enumerate(choices):
        if len(near) == 1 and choices[near[0]] == [e]:
            a, b = endpoints[e][0], endpoints[near[0]][0]
            adj[a].add(b)
            adj[b].add(a)
    seen = set()
    for i in range(n):
        if i in seen or np.isfinite(counts[i]):
            continue
        component, stack, known = set(), [i], set()
        while stack:
            j = stack.pop()
            if j in component:
                continue
            component.add(j)
            for other in adj[j]:
                if np.isfinite(counts[other]):
                    known.add(int(counts[other]))
                elif other not in component:
                    stack.append(other)
        seen.update(component)
        if len(known) == 1:
            for j in component:
                counts[j] = next(iter(known))
                sources[j] = 'connected'
    feats.attrs['lane_count'] = counts
    feats.attrs['lane_source'] = np.array(sources, dtype='<U16')
    feats.attrs['lane_osm_way'] = matched
