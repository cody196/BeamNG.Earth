"""Long usable ramp lanes and regional travel-lane gaps, independent of ramp guidance."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import geodesy
import roads
import roadmesh
import highway_markings as markings
import grading
import surface
from test_roads import features, rules, FRAME, LAT, LON, flat
from test_grading import FakeMD


def interchange(entrance=False, reverse=False):
    ramp = [(300, 100), (200, 80), (150, 20), (-20, 10)] if entrance else [
        (300, 100), (400, 80), (450, 20), (650, 10)]
    direction = -1. if entrance else 1.
    f = features([[(-600, 100), (200, 100)], [(200, 100), (300, 100)], [(300, 100), (850, 100)],
                  ramp[::-1] if reverse else ramp], ['motorway']*4, ids=['upstream', 'before', 'after', 'ramp'])
    f.rules['oneway'] = rules([(0, 1.), (1, 1.), (2, 1.), (3, -direction if reverse else direction)], 'float')
    f.rules['subclass'] = rules([(3, 'link')])
    return f


def relocate(f, lat, lon):
    f.lonlat[:, 0] = lon+(f.lonlat[:, 0]-LON)*np.cos(np.radians(LAT))/np.cos(np.radians(lat))
    f.lonlat[:, 1] += lat-LAT
    return geodesy.EnuFrame(lat, lon, 0.)


class AuxiliaryLaneTest(unittest.TestCase):
    def test_exit_and_entrance_have_200_m_full_width_plus_70_m_taper(self):
        for entrance in (False, True):
            for reverse in (False, True):
                f = interchange(entrance, reverse)
                source, (_, zones, _, bands) = roads.cached_ramp_layout(f)
                self.assertEqual(len(bands), 1)
                band = bands[0]
                guide = band['guide']
                arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(guide[:, :2], axis=0), axis=1))]
                self.assertAlmostEqual(arc[-1], 270., delta=.04)
                self.assertAlmostEqual(arc[-1]-arc[band['taper']], 200., delta=2.)
                self.assertAlmostEqual(band['widths'][0], 3.2)
                self.assertAlmostEqual(max(band['widths']), 6.8)
                dots = next(z['line'] for runs in zones.values() for z in runs if z['mode'] == 'dotted')
                self.assertGreater(np.linalg.norm(np.diff(dots, axis=0), axis=1).sum(), 270.)
                np.testing.assert_allclose(dots[0], guide[0, :2], atol=1e-9,
                                           err_msg='dots start at the taper, filling its former blank divider')
                # Every dotted segment lies on the through/auxiliary divider, not on the taper's outer edge.
                self.assertLess(roads._seg_dist(dots[:30], guide[:-1, :2], guide[1:, :2]).min(1).max(), .03)
                la, lo, _ = source.enu_to_geodetic(guide[0, 0], guide[0, 1], guide[0, 2])
                x, _, _ = FRAME.geodetic_to_enu(la, lo, 0.)
                self.assertAlmostEqual(x, 570. if entrance else 30., delta=.7)

    def test_extension_is_graded_and_painted_as_asphalt(self):
        f = interchange()
        parts = roads.auxiliary_parts(f, 3)
        self.assertEqual(len(parts), 1)
        g = grading.Grader(FRAME, FakeMD(f), flat)
        plans = g._cell_plans(__import__('mapcells').cell_of(LAT, LON))
        self.assertTrue(any(':aux' in fid for fid, _ in plans))
        x, y = np.meshgrid(np.arange(100., 181., 1.), np.arange(85., 106., 1.))
        la, lo, _ = FRAME.enu_to_geodetic(x, y, 0.)
        material = surface.paint_roads(np.full(x.shape, surface.GRASS, np.uint8), la, lo, [f], 1.)
        self.assertEqual(material[7, 40], surface.ASPHALT, 'new outer shoulder has asphalt ground material')
        z = g.apply(la, lo, np.zeros(x.shape))
        self.assertGreater(z[7, 40], 9.9, 'physics ground supports the widened lane')

    def test_layout_and_dash_phase_stay_consistent_between_tiles(self):
        f = interchange()
        chunks = roads.build_tile(FRAME, 0, 0, [f], flat)+roads.build_tile(FRAME, 1, 0, [f], flat)
        guidance = [c for c in chunks if c.get('ramp_guidance')]
        self.assertTrue(guidance)
        self.assertTrue(all(c.get('dash') == 1.2 and c.get('gap') == 2.8 for c in guidance))
        # At x=256 both overlapping tiles retain the same UV coordinate on the dotted divider.
        values = []
        for c in guidance:
            p = np.asarray(c['n'])
            arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(p[:, :2], axis=0), axis=1))]
            if p[:, 0].min() <= 256. <= p[:, 0].max():
                order = p[:, 0].argsort()
                at = np.interp(256., p[order, 0], arc[order])
                values.append((c['uv_start']+at)/c['tl'])
        self.assertGreaterEqual(len(values), 2)
        self.assertLess(max(values)-min(values), .002)

    def test_nearby_interchange_limits_lane_length(self):
        node = np.array([300., 0., 0.])
        line = np.c_[np.arange(0., 601., 2.), np.zeros(301), np.zeros(301), np.zeros(301), np.ones(301)]
        band = roads._auxiliary_lane(node, np.array([1., 0.]), [(line, 3.6)], -1., 3.6,
                                     [np.array([180., 0., 0.])])
        guide = band['guide']
        self.assertAlmostEqual(np.linalg.norm(np.diff(guide[:, :2], axis=0), axis=1).sum(), 100.)

    def test_complete_approach_wins_over_partial_neighbour_cell_in_either_order(self):
        full = interchange()
        partial = features([[(200, 100), (300, 100)], [(300, 100), (850, 100)],
                            [(300, 100), (400, 80), (450, 20), (650, 10)]],
                           ['motorway']*3, ids=['before', 'after', 'ramp'])
        partial.rules['oneway'] = rules([(0, 1.), (1, 1.), (2, 1.)], 'float')
        partial.rules['subclass'] = rules([(2, 'link')])
        a = roads.projected_ramp_layout(FRAME, [partial, full])[3]
        b = roads.projected_ramp_layout(FRAME, [full, partial])[3]
        self.assertEqual(len(a), 1)
        np.testing.assert_allclose(a[0]['pts'], b[0]['pts'], atol=1e-8)
        self.assertAlmostEqual(a[0]['guide'][0, 0], 30., delta=.7)

    def test_ramp_dots_share_one_phase_across_curved_source_feature_boundaries(self):
        x = np.linspace(0., 200., 101)
        line = np.c_[x, .001*x*x, np.zeros(len(x))]
        guide = line[:, :2]
        zone = [{'line': guide, 'mode': 'dotted'}]
        look = {**roads.EDGE_LINE, 'edge_side': -1}
        left = roads._merge_edge_runs(line[:51], look, zone)[0]
        right = roads._merge_edge_runs(line[50:], look, zone)[0]
        a = roads._chunk(left[0], .25, left[1], line[:51])
        b = roads._chunk(right[0], .25, right[1], line[50:])
        length = np.linalg.norm(np.diff(np.asarray(a['n'])[:, :2], axis=0), axis=1).sum()
        self.assertAlmostEqual(a['uv_start']+length, b['uv_start'], delta=.005)
        self.assertEqual(a['tl'], 4.0)
        self.assertEqual(b['tl'], 4.0)

    def test_exit_and_entrance_use_the_same_pattern_in_both_source_orders(self):
        for entrance in (False, True):
            for reverse in (False, True):
                f = interchange(entrance, reverse)
                chunks = [c for tx in (0, 1, 2) for c in roads.build_tile(FRAME, tx, 0, [f], flat)]
                dots = [c for c in chunks if c.get('ramp_guidance')]
                self.assertTrue(dots)
                for c in dots:
                    self.assertEqual(c['w'], .35)
                    self.assertEqual(c['tl'], 4.0)
                    self.assertEqual((c['dash'], c['gap']), (1.2, 2.8))

    def test_exit_stripes_have_exact_length_and_gap_even_when_a_chunk_splits_a_stripe(self):
        reference = np.array([[0., 0., 0.], [99., 0., 0.]])
        zone = [{'line': reference[:, :2], 'mode': 'dotted', 'is_exit': True}]
        look = {**roads.EDGE_LINE, 'edge_side': -1}
        chunks = []
        for a, b in ((0., 44.5), (44.5, 99.)):
            line = np.array([[a, 0., 0.], [b, 0., 0.]])
            style, paint = roads._merge_edge_runs(line, look, zone)[0]
            chunks.append(roads._chunk(style, style['w'], paint, reference))
        spans = []
        for left, right, _, material, _, _ in roadmesh.ribbons(chunks):
            self.assertEqual(material, 'line_white')
            np.testing.assert_allclose(np.linalg.norm(left-right, axis=1), .35, atol=1e-9)
            spans.append((left[0, 0], left[-1, 0]))
        merged = []
        for a, b in sorted(spans):
            if merged and abs(a-merged[-1][1]) < 1e-8:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        self.assertTrue(all(abs(b-a-1.2) < 1e-8 for a, b in merged[1:-1]))
        self.assertTrue(all(abs(c-b-2.8) < 1e-8 for (_, b), (c, _) in zip(merged[:-1], merged[1:])))

    def test_adjacent_exit_and_entrance_guides_keep_their_own_phase_references(self):
        line = np.array([[0., 0., 0.], [100., 0., 0.]])
        zones = [{'line': np.array([[0., 0.], [50., 0.]]), 'mode': 'dotted', 'is_exit': True},
                 {'line': np.array([[50., 0.], [100., 0.]]), 'mode': 'dotted', 'is_exit': False}]
        runs = roads._merge_edge_runs(line, {**roads.EDGE_LINE, 'edge_side': -1}, zones)
        self.assertEqual(len(runs), 2)
        self.assertEqual((runs[0][0]['dash'], runs[0][0]['gap']), (1.2, 2.8))
        self.assertEqual((runs[1][0]['dash'], runs[1][0]['gap']), (1.2, 2.8))
        self.assertIs(runs[0][0]['uv_reference'], zones[0]['line'])
        self.assertIs(runs[1][0]['uv_reference'], zones[1]['line'])
        np.testing.assert_allclose(runs[0][1][-1], runs[1][1][0])

    def test_reversed_guidance_chunks_render_identical_stripes_without_phase_breaks(self):
        for backwards in (False, True):
            reference = np.array([[0., 0., 0.], [99., 0., 0.]])
            if backwards:
                reference = reference[::-1]
            zones = [{'line': reference[:, :2], 'mode': 'dotted'}]
            look = {**roads.EDGE_LINE, 'edge_side': -1}
            baseline = None
            for split in (False, True):
                chunks = []
                ranges = [(0., 42.5), (42.5, 44.5), (44.5, 99.)] if split else [(0., 99.)]
                for index, (a, b) in enumerate(ranges):
                    line = np.array([[a, 0., 0., 0., 1.], [b, 0., 0., 0., 1.]])
                    if index % 2 == 0:
                        line = line[::-1].copy()
                        line[:, 3:5] *= -1
                    style, paint = roads._merge_edge_runs(line, look, zones)[0]
                    chunks.append(roads._chunk(style, style['w'], paint, reference))
                spans = []
                for left, right, *_ in roadmesh.ribbons(chunks):
                    np.testing.assert_allclose(np.linalg.norm(left-right, axis=1), .35, atol=1e-9)
                    spans.append((left[:, 0].min(), left[:, 0].max()))
                merged = []
                for a, b in sorted(spans):
                    if merged and a <= merged[-1][1]+1e-8:
                        merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
                    else:
                        merged.append((a, b))
                self.assertTrue(all(abs(b-a-1.2) < 1e-8 for a, b in merged[1:-1]))
                self.assertTrue(all(abs(c-b-2.8) < 1e-8 for (_, b), (c, _) in zip(merged[:-1], merged[1:])))
                if baseline is None:
                    baseline = merged
                else:
                    np.testing.assert_allclose(merged, baseline, atol=1e-8)

    def test_rendered_dots_cover_the_full_taper_on_exit_and_entrance(self):
        for entrance in (False, True):
            for reverse in (False, True):
                f = interchange(entrance, reverse)
                _, _, _, bands = roads.projected_ramp_layout(FRAME, [f])
                band = bands[0]
                guide = band['guide'][:, :2]
                direction = guide[band['taper']]-guide[0]
                taper = np.linalg.norm(direction)
                direction /= taper
                chunks = [c for tx in (0, 1, 2) for c in roads.build_tile(FRAME, tx, 0, [f], flat)
                          if c.get('ramp_guidance')]
                spans = []
                for left, right, *_ in roadmesh.ribbons(chunks):
                    at = (((left+right)/2)-guide[0]) @ direction
                    a, b = max(0., at.min()), min(taper, at.max())
                    if b-a > 1e-4:
                        spans.append((a, b))
                merged = []
                for a, b in sorted(spans):
                    if merged and a <= merged[-1][1]+.01:
                        merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
                    else:
                        merged.append((a, b))
                self.assertTrue(merged, 'the taper contains painted guidance')
                self.assertLessEqual(merged[0][0], 2.81)
                self.assertLessEqual(taper-merged[-1][1], 2.81)
                self.assertTrue(all(c-b <= 2.81 for (_, b), (c, _) in zip(merged[:-1], merged[1:])),
                                'the taper has only normal dotted gaps, without a long unpainted section')


