"""Follow cached road centrelines for streaming, without doing network I/O on poses.

The likely continuation follows the current carriageway and mapped connectors. This
is a loading hint, not navigation: forks prefer the through road and are reconsidered
as the vehicle turns. Crossings without a shared connector never become junctions.
"""
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import math
import time

import numpy as np

import mapcells

DRIVE = {"motorway", "trunk", "primary", "secondary", "tertiary", "residential",
         "unclassified", "living_street", "service", "unknown", "raceway", "track"}
SKIP = {"driveway", "parking_aisle", "sidewalk", "crosswalk", "cycle_crossing"}
STEP_M = 128.0
MATCH_M = 65.0
MAX_CELLS = 32


def lengths(p):
    return np.r_[0., np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]


def sample(path, distances):
    p = np.asarray(path, float)
    s = lengths(p)
    return np.column_stack([np.interp(distances, s, p[:, i]) for i in (0, 1)])


def clip_path(path, distance):
    p = np.asarray(path, float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 2 or not np.isfinite(p).all():
        return ()
    s = lengths(p)
    if s[-1] <= 0.:
        return ()
    ds = np.r_[np.arange(0., min(distance, s[-1]), STEP_M), min(distance, s[-1])]
    return tuple(map(tuple, sample(p, ds)))


def nearest(p, point):
    ab = np.diff(p, axis=0)
    t = np.clip(((point-p[:-1])*ab).sum(1) / np.maximum((ab*ab).sum(1), 1e-12), 0., 1.)
    q = p[:-1] + t[:, None]*ab
    d = np.linalg.norm(q-point, axis=1)
    k = int(d.argmin())
    return float(d[k]), k, q[k]


def remaining(path, x, y):
    """Trim a prior hint to the moving car, rejecting stale/off-road hints."""
    if len(path) < 2:
        return ()
    p = np.asarray(path, float)
    if p.ndim != 2 or p.shape[1] != 2 or not np.isfinite(p).all():
        return ()
    d, k, q = nearest(p, np.array([x, y]))
    if d > MATCH_M:
        return ()
    out = np.vstack(([x, y], q, p[k+1:]))
    return tuple(map(tuple, out))


@dataclass
class Edge:
    start: str
    end: str
    fid: str
    cls: str
    link: bool
    p: np.ndarray


def _value(table, row, at, default=0):
    if table is not None:
        for r in table.rows(row):
            if table.start[r] <= at <= table.end[r]:
                return table.value[r]
    return default


def edges(frame, cells):
    out, seen = [], set()
    for f in cells:
        if f is None:
            continue
        for i, raw_id in enumerate(f.ids):
            fid = str(raw_id)
            if fid in seen:
                continue
            seen.add(fid)
            cls = str(f.attrs.get("class", ["unknown"]*len(f))[i])
            sub = str(_value(f.rules.get("subclass"), i, .5, ""))
            if cls not in DRIVE or sub in SKIP:
                continue
            # Source geometry already carries highway bends and is much cheaper than
            # fitting/draping a render mesh just to decide what to load next.
            parts = f.parts(i)
            if not parts or not parts[0] or len(parts[0][0]) < 2:
                continue
            ll = np.asarray(parts[0][0], float)
            e, n, _ = frame.geodetic_to_enu(ll[:, 1], ll[:, 0], 0.)
            p = np.c_[e, n]
            s = lengths(p)
            if s[-1] < 1.:
                continue
            marks = {0.: fid+":0", 1.: fid+":1"}
            con = f.rules.get("connectors")
            if con is not None:
                for r in con.rows(i):
                    marks[float(np.clip(con.start[r], 0., 1.))] = "c:"+str(con.value[r])
            # One-way changes are also cut, preserving the direction of each range.
            ow = f.rules.get("oneway")
            if ow is not None:
                for r in ow.rows(i):
                    for at in (float(ow.start[r]), float(ow.end[r])):
                        marks.setdefault(at, fid+":"+str(at))
            order = sorted(marks)
            for a, b in zip(order, order[1:]):
                lo, hi = a*s[-1], b*s[-1]
                if hi-lo < .1:
                    continue
                ds = np.r_[lo, s[(s > lo) & (s < hi)], hi]
                line = np.c_[np.interp(ds, s, p[:, 0]), np.interp(ds, s, p[:, 1])]
                direction = float(_value(ow, i, (a+b)/2))
                if direction >= 0:
                    out.append(Edge(marks[a], marks[b], fid, cls, sub == "link", line))
                if direction <= 0:
                    out.append(Edge(marks[b], marks[a], fid, cls, sub == "link", line[::-1]))
    return out


def trace(frame, cells, x, y, vx, vy, distance):
    graph = edges(frame, cells)
    speed = math.hypot(vx, vy)
    if not graph or speed < 1.:
        return ()
    heading, point = np.array([vx, vy])/speed, np.array([x, y])
    best = None
    for index, edge in enumerate(graph):
        d, k, q = nearest(edge.p, point)
        tangent = edge.p[k+1]-edge.p[k]
        norm = np.linalg.norm(tangent)
        cos = float(tangent@heading/norm) if norm > 1e-6 else -1.
        if d <= MATCH_M and cos > .15:
            score = d+30.*(1.-cos)
            if best is None or score < best[0]:
                best = score, index, k, q
    if best is None:
        return ()
    _, index, k, q = best
    edge = graph[index]
    path = [point, q, *edge.p[k+1:]]
    used = {index}
    outgoing = defaultdict(list)
    for j, item in enumerate(graph):
        outgoing[item.start].append(j)
    travelled = float(lengths(np.asarray(path))[-1])
    for _ in range(128):
        if travelled >= distance:
            break
        tangent = edge.p[-1]-edge.p[-2]
        tangent /= max(float(np.linalg.norm(tangent)), 1e-9)
        choices = []
        for j in outgoing[edge.end]:
            if j in used:
                continue
            nxt = graph[j]
            if np.linalg.norm(nxt.p[0]-edge.p[-1]) > 12.:
                continue
            vec = nxt.p[1]-nxt.p[0]
            cos = float(vec@tangent/max(float(np.linalg.norm(vec)), 1e-9))
            if cos < -.5:
                continue
            score = cos + .15*(nxt.fid == edge.fid) + .12*(nxt.cls == edge.cls) - .2*(nxt.link and not edge.link)
            choices.append((score, -j, j))
        if not choices:
            break
        index = max(choices)[2]
        edge = graph[index]
        used.add(index)
        path.extend(edge.p)
        travelled += float(lengths(edge.p)[-1])
    return clip_path(path, distance)


class Planner:
    """One background reader. get() is cheap and never waits for source data."""
    def __init__(self, md, max_m):
        self.md, self.max_m = md, max_m
        self.pool = ThreadPoolExecutor(1, thread_name_prefix="road-lookahead")
        self.states = OrderedDict()

    def close(self):
        for _, future, _ in self.states.values():
            future.cancel()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def get(self, anchor, x, y, vx, vy):
        speed = math.hypot(vx, vy)
        if self.md is None or speed < 8.:
            return ()
        now = time.monotonic()
        state = self.states.get(anchor.id)
        path = ()
        if state is not None:
            if state[1].done():
                try:
                    path = remaining(state[1].result(), x, y)
                except Exception:
                    pass
            else:
                path = remaining(state[2], x, y)
        # Recheck a fork as the car turns; refuse a hint whose first step is behind it.
        if len(path) > 2:
            dx, dy = path[min(2, len(path)-1)][0]-x, path[min(2, len(path)-1)][1]-y
            if dx*vx+dy*vy < 0:
                path = ()
        if state is None or (state[1].done() and now-state[0] >= 1.):
            future = self.pool.submit(self._plan, anchor.frame, x, y, vx, vy, path)
            self.states[anchor.id] = (now, future, path)
            self.states.move_to_end(anchor.id)
            while len(self.states) > 4:
                _, old = self.states.popitem(last=False)
                old[1].cancel()
        return path

    def _plan(self, frame, x, y, vx, vy, prior):
        cells, asked = [], set()
        path = prior or ((x, y),)
        # Grow through cached cells at the frontier. Missing cells are fetched by
        # download_ahead; this reader never starts a download of its own.
        for _ in range(4):
            points = list(path[::2]) + [path[-1]]
            for px, py in points:
                la, lo, _ = frame.enu_to_geodetic(px, py, 0.)
                pad = 320./111320.
                lp = pad/max(.05, math.cos(math.radians(float(la))))
                for key in mapcells.cells_for_bbox(float(la)-pad, float(lo)-lp, float(la)+pad, float(lo)+lp):
                    if key in asked or len(asked) >= MAX_CELLS:
                        continue
                    asked.add(key)
                    if self.md.has(key, "roads"):
                        cells.append(self.md.cell(key, layers=("roads",), kind="prefetch").layers.get("roads"))
            fresh = trace(frame, cells, x, y, vx, vy, min(self.max_m, math.hypot(vx, vy)*60.))
            if not fresh or fresh == path:
                break
            path = fresh
        return fresh
