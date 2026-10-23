"""Highway port integration with 1.6's terrain roads and nonblocking cell reads."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import mapcells
import polygon
import roads
import surface
from test_roads import FRAME, features, rules, flat


class HighwayGroundTest(unittest.TestCase):
    def test_ramp_returns_appear_in_photos_materials_and_near_masks(self):
        f = features([[(10, 100), (150, 100), (300, 100)], [(150, 100), (150, 240)]], ['primary', 'motorway'])
        f.rules['oneway'] = rules([(1, -1.)], 'float')
        f.rules['subclass'] = rules([(1, 'link')])
        corners = roads.ground_corners(FRAME, [f])
        self.assertEqual(len(corners), 2)
        canvas = np.full((320, 320, 3), 200, np.uint8)
        photo = surface.photo_roads(canvas, FRAME, 0., 0., 320., [f])
        fake = SimpleNamespace(urban=None, roads=lambda la, lo: ([f], True))
        mask = surface.road_mask(FRAME, 0., 0., 320., 320, fake)
        x, y = np.meshgrid(np.arange(320)+.5, 319.5-np.arange(320))
        lat, lon, _ = FRAME.enu_to_geodetic(x, y, 0.)
        materials = surface.paint_roads(np.full(x.shape, surface.GRASS, np.uint8), lat, lon, [f], 1.)
        for corner in corners:
            # A concave return's vertex mean can lie outside it. Check pixel centres
            # inside the actual polygon, at least one pixel away from its edges.
            ring = np.asarray(corner['fill'])[:, :2]
            points = np.c_[x.ravel(), y.ravel()]
            inside = polygon.contains_points(ring, points)
            candidates = np.flatnonzero(inside)
            distance = roads._seg_dist(points[candidates], ring, np.roll(ring, -1, axis=0)).min(1)
            candidates = candidates[distance > 1.]
            self.assertGreater(len(candidates), 0)
            self.assertGreater(mask.ravel()[candidates].min(), 200)
            self.assertLess(photo.reshape(-1, 3)[candidates].max(), 120)
            self.assertTrue((materials.ravel()[candidates] == surface.ASPHALT).all())
        with patch.object(roads, 'ROADS_IN_GROUND', True):
            chunks = roads.build_tile(FRAME, 0, 0, [f], flat)
        self.assertFalse(any(c.get('poly') and not c.get('turn_arrow') for c in chunks))

    def test_missing_curve_neighbors_are_queued_without_blocking_or_using_partial_geometry(self):
        key = mapcells.CellKey(14, 1000, 1000)
        neighbour = mapcells.CellKey(14, 1001, 1000)
        context = SimpleNamespace(required=lambda f: [key, neighbour])
        feats = SimpleNamespace(_road_context=context)
        cached = {key}
        calls = []
        def cell(k, **kwargs):
            calls.append(k)
            self.assertIn(k, cached, 'a cache miss must never trigger a synchronous fetch')
            return SimpleNamespace(layers={'roads': feats})
        obj = object.__new__(surface.Surface)
        obj.md = SimpleNamespace(has=lambda k, layer: k in cached, cell=cell)
        queued = []
        obj._queue = lambda k, layers: queued.append((k, layers))
        with patch.object(mapcells, 'cells_for_points', return_value=[key]):
            self.assertEqual(obj.roads(np.array([40.]), np.array([-90.])), ([], False))
            self.assertEqual(queued, [(neighbour, ('roads',))])
            cached.add(neighbour)
            self.assertEqual(obj.roads(np.array([40.]), np.array([-90.])), ([feats], True))


if __name__ == '__main__':
    unittest.main()
