"""User-specified US paint dimensions, geographic selection and rendered dash continuity."""
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geodesy
import highway_markings as hm
import roadmesh
import roads


# Independent expectations transcribed from ROAD_IMPROVEMENT_NOTES.md.
CASES = {
    'MI': ((42.73, -84.55), (4.5, .4, 11.5), (1.5, .35, 6.), .4),
    'MN': ((44.95, -93.1), (3.1, .3, 12.25), None, .45),
    'WI': ((43.07, -89.4), (5.15, .31, 10.25), (1.25, .3, 2.9), .32),
    'CA': ((38.58, -121.49), (4.6, .35, 10.5), (2.3, .25, 4.9), .25),
    'ID': ((43.62, -116.2), (3., .35, 8.), (1.2, .35, 2.8), .35),
    'KY': ((38.2, -84.87), (3., .35, 8.), (1.2, .35, 2.8), .35),
    'AK': ((64.84, -147.72), (3., .35, 8.), (1.2, .35, 2.8), .35),
    'HI': ((21.3, -157.85), (3., .35, 8.), (1.2, .35, 2.8), .35),
}


def line(a=0., b=200., **kwargs):
    return dict(m='line_dashed_short', w=.12, tl=12., p=21,
                n=[[a, 0., 10.], [b, 0., 10.]], uv_start=a, **kwargs)


def spans(chunks):
    result = []
    for left, right, _, material, _, _ in roadmesh.ribbons(chunks):
        result.append((left[0, 0], left[-1, 0]))
    merged = []
    for a, b in sorted(result):
        if merged and abs(a-merged[-1][1]) < 1e-7:
            merged[-1] = merged[-1][0], b
        else:
            merged.append((a, b))
    return merged


class MarkingProfilesTest(unittest.TestCase):
    def test_multilane_ramp_dashes_follow_the_ramp_profile(self):
        from test_auxiliary_markings import interchange, relocate
        from test_roads import rules, flat
        for state in ('MI', 'MN'):
            f = interchange()
            f.rules['lanes_forward'] = rules([(0, 2), (1, 2), (2, 2), (3, 2)], 'float')
            f.rules['lanes_backward'] = rules([(i, 0) for i in range(4)], 'float')
            frame = relocate(f, *CASES[state][0])
            chunks = roads.build_tile(frame, 0, 0, [f], flat)
            ramp_paint = [c for c in chunks if c.get('ramp_lane') or c.get('ramp_guidance')]
            if state == 'MN':
                self.assertFalse(any(c['m'].startswith('line_dashed') for c in ramp_paint))
            else:
                self.assertTrue(ramp_paint)
                for c in ramp_paint:
                    if c['m'].startswith('line_dashed'):
                        self.assertEqual((c['dash'], c['w'], c['gap']), (1.5, .35, 6.))

    def test_compute_sharing_fingerprint_includes_boundary_data(self):
        import peerwork
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'highway_marking_states.geojson'
            path.write_text('{}', encoding='utf-8')
            before = peerwork.source_id(tmp)
            path.write_text('{"changed":true}', encoding='utf-8')
            self.assertNotEqual(before, peerwork.source_id(tmp))

    def test_geography_and_physical_paint_dimensions(self):
        for state, (location, travel, ramp, solid) in CASES.items():
            with self.subTest(state=state):
                self.assertEqual(str(hm.states(*location)), state)
                frame = geodesy.EnuFrame(*location)
                for flag, expected in ((None, travel), ('ramp_guidance', ramp), ('ramp_lane', ramp)):
                    chunks = hm.apply([line(**({flag: True} if flag else {}))], frame)
                    if expected is None:
                        self.assertEqual(chunks, [])
                        continue
                    dash, width, gap = expected
                    strokes = spans(chunks)
                    self.assertGreater(len(strokes), 6)
                    np.testing.assert_allclose([b-a for a, b in strokes[1:-1]], dash, atol=1e-8)
                    np.testing.assert_allclose([a-b for (_, b), (a, _) in zip(strokes, strokes[1:])], gap, atol=1e-8)
                    for left, right, _, material, _, _ in roadmesh.ribbons(chunks):
                        self.assertEqual(material, 'line_white')
                        np.testing.assert_allclose(np.linalg.norm(left-right, axis=1), width, atol=1e-8)
                for material in ('line_white', 'line_yellow'):
                    chunk = line()
                    chunk['m'] = material
                    self.assertEqual(hm.apply([chunk], frame)[0]['w'], solid)

    def test_all_other_states_and_dc_use_us_fallback(self):
        abbreviations = {state for state, *_ in hm._polygons()}
        self.assertEqual(len(abbreviations), 51)
        self.assertEqual(set(hm.PROFILES), {'MI', 'MN', 'WI', 'CA'})
        frame = geodesy.EnuFrame(40., -90.)
        for state in abbreviations - set(CASES):
            with self.subTest(state=state), patch.object(hm, 'states', side_effect=lambda la, lo, s=state: np.full(np.shape(la), s)):
                result = hm.apply([line()], frame)[0]
                self.assertEqual((result['dash'], result['w'], result['gap']), (3., .35, 8.))

    def test_neighboring_countries_are_not_given_us_dimensions(self):
        for location in ((42.31, -83.03), (49.32, -123.1), (32.51, -117.03), (51.5, -.12)):
            with self.subTest(location=location):
                self.assertEqual(str(hm.states(*location)), '')
                chunk = line()
                self.assertEqual(hm.apply([chunk], geodesy.EnuFrame(*location)), [chunk])

    def test_dash_phase_survives_tile_cuts_and_bridge_height(self):
        for location, _, _, _ in CASES.values():
            frame = geodesy.EnuFrame(*location)
            whole = hm.apply([line(fixed=True)], frame)
            split = hm.apply([line(a, b, fixed=True) for a, b in ((0., 43.17), (43.17, 101.75), (101.75, 200.))], frame)
            np.testing.assert_allclose(spans(whole), spans(split), atol=1e-8)
            for *_, z in roadmesh.ribbons(split):
                np.testing.assert_allclose(z, 10.)

    def test_actual_indiana_michigan_border_splits_profile_not_geometry(self):
        frame = geodesy.EnuFrame(41.759, -85.)
        chunk = line()
        chunk['n'] = [[0., -1000., 7.], [0., 1000., 9.]]
        result = hm.apply([chunk], frame)
        self.assertEqual([r['dash'] for r in result], [3., 4.5])
        np.testing.assert_allclose(result[0]['n'][-1], result[1]['n'][0])
        self.assertEqual(result[0]['n'][0], chunk['n'][0])
        self.assertEqual(result[-1]['n'][-1], chunk['n'][-1])
        self.assertAlmostEqual(result[1]['uv_start'], result[0]['n'][-1][1]+1000.)

    def test_stop_bars_and_turn_arrows_retain_their_own_dimensions(self):
        frame = geodesy.EnuFrame(*CASES['MN'][0])
        stop = line(keep_dimensions=True)
        stop.update(m='line_white', w=.45)
        arrow = dict(m='line_turn_arrow', poly=[[0., 0., 0.], [1., 1., 0.], [2., 0., 0.]], turn_arrow=True)
        self.assertEqual(hm.apply([stop, arrow], frame), [stop, arrow])

    def test_double_yellow_lines_remain_separate_after_widening(self):
        for location, _, _, width in CASES.values():
            chunks = []
            for side in (-1, 1):
                chunk = line(centre_pair=side)
                chunk.update(m='line_yellow', n=[[0., side*.12, 0.], [100., side*.12, 0.]])
                chunks.append(chunk)
            ribbons = roadmesh.ribbons(hm.apply(chunks, geodesy.EnuFrame(*location)))
            lower_top = np.max(np.r_[ribbons[0][0][:, 1], ribbons[0][1][:, 1]])
            upper_bottom = np.min(np.r_[ribbons[1][0][:, 1], ribbons[1][1][:, 1]])
            self.assertAlmostEqual(upper_bottom-lower_top, .12)


if __name__ == '__main__':
    unittest.main()
