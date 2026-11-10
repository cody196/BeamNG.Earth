"""US state-entry boards: offline Census boundaries, directed roads, one owner per sign.

Artwork is a representative interpretation per state, not a surveyed sign inventory.
The States 500K boundaries are generalized: positions remain estimates. Hawaii and
DC are not part of the 49-state set; international road entries (including Alaska)
are supported. Ground placement follows bridges/tunnels to their receiving bank.
"""
from collections import defaultdict
from functools import lru_cache
import gzip
import json
import math
from pathlib import Path

import numpy as np

import exitsigns
import roads
import signmesh
import signroads
import signstates

DATA = Path(__file__).with_name('data')
CLASSES = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary'}
SEARCH_M = 1600.0
SETBACK_M = 25.0
CLEARANCE_M = 1.5
VERSION = 'state-welcome-v1'


@lru_cache(maxsize=1)
def designs():
    return json.loads((DATA / 'welcome_signs.json').read_text(encoding='utf-8'))['states']


class Borders:
    def __init__(self, data):
        polygons, edges = [], []
        self.grid = defaultdict(list)
        for feature in data['features']:
            state = feature['properties']['STUSAB']
            g = feature['geometry']
            for poly in ([g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']):
                rings = [np.asarray(r, float) for r in poly]
                polygons.append((state, rings[0].min(0), rings[0].max(0), rings))
                for ring in rings:
                    for a, b in zip(ring[:-1], ring[1:]):
                        # Adjacent states generally share edges; quantization only
                        # de-duplicates the index, never moves the source geometry.
                        edges.append((a, b))
        self.polygons = signstates._Polygons(polygons)
        self.edges = np.asarray(edges)
        self.low = self.edges.min(1)
        self.high = self.edges.max(1)
        for i, (lo, hi) in enumerate(zip(self.low, self.high)):
            for x in range(math.floor(lo[0]), math.floor(hi[0]) + 1):
                for y in range(math.floor(lo[1]), math.floor(hi[1]) + 1):
                    self.grid[x, y].append(i)

    def states(self, points):
        points = np.asarray(points).reshape(-1, 2)
        return signstates.lookup(points[:, 1], points[:, 0], self.polygons)

    def nearby(self, lo, hi):
        ix = self._cells(math.floor(lo[0]), math.floor(lo[1]), math.floor(hi[0]), math.floor(hi[1]))
        return self.edges[ix[(self.high[ix] >= lo).all(1) & (self.low[ix] <= hi).all(1)]]

    @lru_cache(maxsize=128)
    def _cells(self, x0, y0, x1, y1):
        return np.asarray(sorted({i for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)
                                  for i in self.grid.get((x, y), ())}), int)

    def crossings(self, line):
        """Arc positions of all border intersections, including a feature endpoint."""
        lengths = np.linalg.norm(np.diff(line[:, :2], axis=0), axis=1)
        arc = np.r_[0., np.cumsum(lengths)]
        result = []
        nearby = self.nearby(line[:, 2:].min(0), line[:, 2:].max(0))
        if not len(nearby):
            return result
        low, high = nearby.min(1), nearby.max(1)
        for i, (a, b) in enumerate(zip(line[:-1], line[1:])):
            if lengths[i] < 1e-5:
                continue
            edges = nearby[(high >= np.minimum(a[2:], b[2:])).all(1) & (low <= np.maximum(a[2:], b[2:])).all(1)]
            if not len(edges):
                continue
            delta = b[2:] - a[2:]
            e = edges[:, 1] - edges[:, 0]
            q = edges[:, 0] - a[2:]
            cross = lambda u, v: u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0]
            den = cross(delta, e)
            good = abs(den) > 1e-15
            t = cross(q, e) / np.where(good, den, 1.)
            u = cross(q, delta) / np.where(good, den, 1.)
            good &= (t >= -1e-8) & (t <= 1 + 1e-8) & (u >= -1e-8) & (u <= 1 + 1e-8)
            result.extend(arc[i] + np.clip(t[good], 0, 1) * lengths[i])
        # Opposite sides of a shared boundary and adjacent segments at a node
        # must produce a single crossing, not two welcome boards.
        out = []
        for s in sorted(result):
            if not out or s - out[-1] > 1.0:
                out.append(float(s))
        return out


@lru_cache(maxsize=1)
def borders():
    with gzip.open(DATA / 'welcome_states.geojson.gz', 'rt', encoding='utf-8') as f:
        return Borders(json.load(f))


def _line(frame, ring):
    e, n, _ = frame.geodetic_to_enu(ring[:, 1], ring[:, 0], 0.)
    return np.c_[e, n, ring[:, :2]]


def _rows(frame, feats, context, left_hand):
    rows = []
    specs = signroads.cell_specs(feats, context.urban, context.widths, left_hand)
    for i, sp in enumerate(specs):
        if sp is None or sp.cls not in CLASSES or signroads.is_link(feats, i):
            continue
        for part in feats.parts(i):
            for ring in part:
                if len(ring) < 2:
                    continue
                line = _line(frame, ring)
                for direction in ((-1 if sp.dir < 0 else 1,) if sp.oneway else (1, -1)):
                    path = line[::direction]
                    if np.linalg.norm(np.diff(path[:, :2], axis=0), axis=1).sum() > .1:
                        rows.append((str(feats.ids[i]), sp, path))
    return sorted(rows, key=lambda r: (r[0], tuple(r[2][0])))


def _extend(row, rows, backwards=False, distance=SEARCH_M):
    """Follow a continuous road across source-feature splits; do not extrapolate.

    Stop at ambiguous forks. Reversed two-way edges cannot send the search back
    along the same road. This also carries crossings on bridge-only features to
    an actual ground road on the receiving side.
    """
    path = row[2][::-1] if backwards else row[2]
    path = path.copy()
    used = {id(row)}
    length = np.linalg.norm(np.diff(path[:, :2], axis=0), axis=1).sum()
    while length < distance:
        heading = path[-1, :2] - path[-2, :2]
        heading /= max(np.linalg.norm(heading), 1e-9)
        choices = []
        for other in rows:
            if id(other) in used:
                continue
            p = other[2][::-1] if backwards else other[2]
            if np.linalg.norm(p[0, :2] - path[-1, :2]) > 1.0:
                continue
            d = p[1, :2] - p[0, :2]
            alignment = float(d @ heading) / max(np.linalg.norm(d), 1e-9)
            if alignment > .5:
                choices.append((alignment, other, p))
        choices.sort(key=lambda c: (-c[0], c[1][0]))
        if not choices or (len(choices) > 1 and choices[0][0] - choices[1][0] < .1):
            break
        _, other, p = choices[0]
        used.add(id(other))
        path = np.vstack([path, p[1:]])
        length += np.linalg.norm(np.diff(p[:, :2], axis=0), axis=1).sum()
    return path


def _state_at(index, frame, xy):
    la, lo, _ = frame.enu_to_geodetic(xy[0], xy[1], 0.)
    return str(index.states([[lo, la]])[0])


def plans(frame, rows, pavements, index=None):
    index = index or borders()
    result = []
    outlines = exitsigns._outlines(pavements)
    for row in rows:
        _, sp, line = row
        hits = index.crossings(line)
        if not hits:
            continue
        original_length = np.linalg.norm(np.diff(line[:, :2], axis=0), axis=1).sum()
        before = _extend(row, rows, True, original_length + 100.)
        after = _extend(row, rows, distance=original_length + SEARCH_M)
        extra = np.linalg.norm(np.diff(before[:, :2], axis=0), axis=1).sum() - original_length
        path = np.vstack([before[::-1][:-len(line)], after]) if extra > .01 else after
        length = np.linalg.norm(np.diff(path[:, :2], axis=0), axis=1).sum()
        for hit in hits:
            station = hit + extra
            # A feature ending at the boundary needs its real continuation. A
            # dangling road endpoint or a tangential touch is not a crossing.
            if station < 3 or station + 3 > length:
                continue
            old = _state_at(index, frame, exitsigns._station(path, station - 3)[0])
            state = _state_at(index, frame, exitsigns._station(path, station + 3)[0])
            if old == state or state not in designs():
                continue
            crossing, crossing_dir, _ = exitsigns._station(path, station)
            # Empty prior state denotes international entry. Avoid offshore
            # coast edges by requiring a continuous road on both sides.
            board_w = designs()[state]['width']
            for travel_m in np.arange(SETBACK_M, min(SEARCH_M, length - station) + .01, 15.):
                at, travel, _ = exitsigns._station(path, station + travel_m)
                if _state_at(index, frame, at) != state:
                    break
                # Use a real ground ribbon; bridge and tunnel lines alone do
                # not permit planting poles in a river or over a tunnel.
                ground = exitsigns._nearest(at[:2], pavements)
                if ground is None or ground[0] > 1.5 or abs(float(ground[7] @ travel)) < .8:
                    continue
                right = np.array([travel[1], -travel[0]])
                width = ground[2].width
                radius = board_w / 2 + CLEARANCE_M
                for gap in (0., 2., 4.):
                    xy = at[:2] + right * (width / 2 + radius + gap)
                    if _state_at(index, frame, xy) != state or not exitsigns._clear(xy, radius, outlines):
                        continue
                    result.append(dict(state=state, xy=xy, travel=travel, road_point=at[:2],
                                       crossing=crossing[:2], crossing_dir=crossing_dir))
                    break
                else:
                    continue
                break
    # A border exactly at an Overture connector is found from both features.
    # Distinct incoming carriageways remain independent.
    unique = []
    for p in sorted(result, key=lambda p: (p['state'], *p['crossing'], *p['xy'])):
        if any(p['state'] == q['state'] and np.linalg.norm(p['crossing'] - q['crossing']) < 3.
               and float(p['crossing_dir'] @ q['crossing_dir']) > .95 for q in unique):
            continue
        unique.append(p)
    return unique


def _post_top(style, x):
    """Highest plate edge at the post's normalized x; no pole above an arch."""
    panels = style.get('panels')
    if not panels:
        return 1.
    heights = []
    for panel in panels:
        points = panel['points']
        for a, b in zip(points, points[1:] + points[:1]):
            if abs(b[0] - a[0]) > 1e-9 and min(a[0], b[0]) <= x <= max(a[0], b[0]):
                heights.append(a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))
    return max(heights, default=.5)


def _shaped_panel(mesh, material, panel, w, h, bottom, layer):
    # A state silhouette can sit in front of another panel (Wisconsin).
    # Offset the complete plate to prevent coplanar flickering in the overlap.
    points = np.asarray(panel['points'], float)
    coords = points * [w, h] + [-w/2, bottom]
    front = np.c_[coords[:, 0], np.full(len(points), -.03 - layer*.006), coords[:, 1]]
    back = front + [0., .05, 0.]
    # roadmesh.write -> cdae.write accepts Collada UVs (V up) and performs
    # the conversion to BeamNG's image-row convention. Do not flip V here.
    uv = points
    for triangle in panel['triangles']:
        mesh.face(material, front[triangle], uv[triangle])
        mesh.face(signmesh.METAL, back[triangle][::-1])
    for i in range(len(points)):
        j = (i + 1) % len(points)
        mesh.face(signmesh.METAL, [front[i], back[i], back[j], front[j]])


def build(signs, origin):
    mesh = signmesh.Mesh(origin)
    materials = list(signmesh.MATERIALS)
    for sign in signs:
        style = designs()[sign['state']]
        w, h = style['width'], style['height']
        name = 'bne_welcome_' + sign['state'].lower()
        if name not in materials:
            materials.append(name)
        mesh.transform(sign['centre'], sign['travel'])
        bottom = sign['bottom'] - sign['centre'][2]
        for offset, base in zip((-w * .34, w * .34), sign['bases']):
            top = bottom + h * _post_top(style, offset/w + .5) - .04
            low = base - sign['centre'][2] - .25
            mesh.box(signmesh.METAL, (offset, .10, (low + top) / 2), (.055, .055, (top - low) / 2))
        if style.get('panels'):
            for layer, panel in enumerate(style['panels']):
                _shaped_panel(mesh, materials.index(name), panel, w, h, bottom, layer)
        else:
            mesh.panel_body(w, h, bottom + h / 2, .045)
            mesh.face(materials.index(name), [(-w/2, -.03, bottom), (w/2, -.03, bottom),
                                            (w/2, -.03, bottom+h), (-w/2, -.03, bottom+h)],
                      [(0, 0), (1, 0), (1, 1), (0, 1)])
    if not mesh.t:
        return None
    return (np.asarray(mesh.p), np.asarray(mesh.t), np.asarray(mesh.uv), materials, np.asarray(mesh.tm))


def build_tile(frame, tx, ty, elev, context, decks=(), left_hand=False):
    box = roads.tile_bbox(tx, ty)
    index = borders()
    la, lo, _ = frame.enu_to_geodetic(np.array([box[0]-SEARCH_M, box[2]+SEARCH_M]),
                                    np.array([box[1]-SEARCH_M, box[3]+SEARCH_M]), 0.)
    points = np.c_[lo, la]
    if not len(index.nearby(points.min(0), points.max(0))):
        return None
    feats = context.around(points)
    rows = _rows(frame, feats, context, left_hand)
    pavements = context.pavements(frame, points, left_hand)
    if not rows or not pavements:
        return None
    signs = []
    for plan in plans(frame, rows, pavements, index):
        xy, travel = plan['xy'], plan['travel']
        if not (box[0] <= xy[0] < box[2] and box[1] <= xy[1] < box[3]):
            continue
        w = designs()[plan['state']]['width']
        if exitsigns._on_deck(xy, decks, w/2 + CLEARANCE_M):
            continue
        right = np.array([travel[1], -travel[0]])
        bases = [exitsigns._ground_z(frame, elev, xy + right*s) for s in (-w*.34, w*.34)]
        ground = exitsigns._ground_z(frame, elev, xy)
        road_z = exitsigns._ground_z(frame, elev, plan['road_point'])
        if not np.isfinite([*bases, ground, road_z]).all() or max(bases)-min(bases) > 1.5 or abs(ground-road_z) > 4.:
            continue
        signs.append(dict(plan, centre=np.r_[xy, ground], bases=bases,
                          bottom=max(max(bases)+1.8, road_z+1.8)))
    return build(signs, (box[0], box[1], 0.))
