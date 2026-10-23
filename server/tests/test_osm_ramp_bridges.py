"""Actual OSM attribution ordering and ramp cross-sections across bridge level cuts."""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import osmtags
import overture
import roadcontext
import roadlanes
import roads
import rampsupport
import surface
import roadmesh
import grading
from test_roads import features, rules, FRAME, flat
from test_auxiliary_markings import interchange


class OsmSourceTest(unittest.TestCase):
    def test_route_attribution_cannot_hide_the_geometry_way(self):
        # Source order captured from Exit 3, I-69 NB. The route relation has no lane count.
        f = features([[(0, 0), (1000, 0)]], ['motorway'])
        f.rules['oneway'] = rules([(0, 1.)], 'float')
        f.attrs['src_record'] = np.array(['r15229259@6'])
        f.attrs['osm_sources'] = np.array([json.dumps([
            {'record_id': 'w156641080@16', 'between': None}])])
        osmtags.join(f, {156641080: {'lanes': 2, 'osm_oneway': 'yes'}})
        for urban in (None, lambda la, lo: np.ones(np.shape(la), bool)):
            sp = roads.road_specs(f, urban)[0]
            self.assertEqual(sp.directional_lanes, (2, 0, 0))
            self.assertAlmostEqual(roads.driving_width(sp), 7.2)

    def test_query_keeps_scoped_geometry_sources_not_route_or_name_attribution(self):
        import duckdb
        sources = [dict(dataset='OpenStreetMap', record_id=r, property=p, between=b) for r, p, b in [
            ('r15229259@6', '/routes', None), ('w1@1', '', [0., .5]),
            ('w2@1', '/geometry', [.5, 1.]), ('w9@1', '/names', None)]]
        con = duckdb.connect()
        try:
            value = con.execute(f'SELECT {overture._ROAD_SOURCES} FROM (SELECT ? AS sources)', [sources]).fetchone()[0]
        finally:
            con.close()
        self.assertEqual([s['record_id'] for s in json.loads(value)], ['w1@1', 'w2@1'])

    def test_scoped_lane_change_and_neighbor_tag_union(self):
        def make(tags):
            f = features([[(0, 0), (1000, 0)]], ['motorway'])
            f.rules['oneway'] = rules([(0, 1.)], 'float')
            f.attrs['osm_sources'] = np.array([json.dumps([
                {'record_id': 'w1@1', 'between': [0., .5]},
                {'record_id': 'w2@1', 'between': [.5, 1.]}])])
            return osmtags.join(f, tags)
        a, b = make({1: {'lanes': 2}}), make({2: {'lanes': 3}})
        for cells in ([a, b], [b, a]):
            f = roadcontext.merge(cells)
            sp = roads.road_specs(f)[0]
            ll = f.parts(0)[0][0]
            p = np.column_stack(FRAME.geodetic_to_enu(ll[:, 1], ll[:, 0], 0.))
            p = roads.densify(p, 2.)
            counts = roadlanes.counts(sp, p, FRAME).sum(1)
            self.assertAlmostEqual(counts[0], 2.)
            self.assertAlmostEqual(counts[-1], 3.)
            self.assertLess(abs(np.diff(counts)).max(), .02)

    def test_known_lane_count_is_not_hidden_by_a_longer_source_without_lanes(self):
        f=features([[(0,0),(1000,0)]],['motorway'])
        f.rules['oneway']=rules([(0,1.)],'float')
        f.attrs['osm_sources']=np.array([json.dumps([
            dict(record_id='w1@1',between=[0.,.8]), dict(record_id='w2@1',between=[.8,1.])])])
        osmtags.join(f,{1:{'maxspeed':100.},2:{'lanes':2}})
        self.assertEqual(roads.road_specs(f)[0].lanes,2)


def bridge_exit(entrance=False):
    f = interchange(entrance)
    # Exit: auxiliary lane crosses a bridge at x~40..160; entry: x~400..520.
    f.rules['level'] = rules([(2, 1., 100/550, 220/550)] if entrance else [(0, 1., .8, .95)], 'float')
    f.attrs['osm_lanes'] = np.array([2., 2., 2., 1.])
    return f


class RampBridgeTest(unittest.TestCase):
    def test_ground_and_ramp_paint_use_the_same_urban_cross_section(self):
        f = interchange()
        urban = lambda la, lo: np.ones(np.shape(la), bool)
        source, (_, _, _, bands) = roads.cached_ramp_layout(f, urban_fn=urban)
        p = bands[0]['guide']
        la, lo, _ = source.enu_to_geodetic(p[:, 0], p[:, 1], p[:, 2])
        _, north, _ = FRAME.geodetic_to_enu(la, lo, 0.)
        ll = f.parts(1)[0][0]
        _, centre, _ = FRAME.geodetic_to_enu(ll[:, 1], ll[:, 0], 0.)
        self.assertAlmostEqual(float(centre.mean()-north.mean()), 5.4, delta=.02)

    def test_auxiliary_lane_crosses_bridge_without_ground_paint_or_grade_fill(self):
        for entrance in (False, True):
            f = bridge_exit(entrance)
            source, (_, zones, _, bands) = roads.cached_ramp_layout(f)
            self.assertEqual(len(bands), 1)
            band = bands[0]
            self.assertAlmostEqual(np.linalg.norm(np.diff(band['guide'][:, :2], axis=0), axis=1).sum(), 270., delta=.1)
            pieces = rampsupport.runs(band['pts'], band['supports'])
            self.assertTrue(any(s is not None for s, _ in pieces), 'the auxiliary lane includes the span')
            for a, b in zip(pieces, pieces[1:]):
                np.testing.assert_allclose(a[1][-1], b[1][0], atol=1e-7)
            for support, run in pieces:
                if support is None: continue
                sample = run[len(run)//2]
                la, lo, _ = source.enu_to_geodetic(sample[0], sample[1], sample[2])
                x, y, _ = FRAME.geodetic_to_enu(la, lo, 0.)
                xx, yy = np.meshgrid(x+np.arange(-3., 3., .25), y+np.arange(-3., 3., .25))
                lat, lon, _ = FRAME.enu_to_geodetic(xx, yy, 0.)
                result = surface.paint_roads(np.full(xx.shape, surface.GRASS, np.uint8), lat, lon, [f], .25)
                self.assertNotEqual(result[12, 12], surface.ASPHALT, 'no asphalt painted below the added bridge lane')
            for ll, _ in roads.auxiliary_parts(f, 3):
                p = np.column_stack(source.geodetic_to_enu(ll[:, 1], ll[:, 0], 0.))
                for support in band['supports']:
                    self.assertLess(rampsupport._coverage((p[:-1]+p[1:])/2, support).max(), .01)

    def test_fixed_ramp_deck_and_guidance_share_the_existing_bridge_grade(self):
        for entrance in (False, True):
            f = bridge_exit(entrance)
            decks = []
            for i, sp in enumerate(roads.bridge_specs(f)):
                if sp is None: continue
                for ll in roads.bridge_parts(f, i):
                    p = np.column_stack(FRAME.geodetic_to_enu(ll[:, 1], ll[:, 0], 0.))
                    p = roads.densify(p, 2.)
                    p[:, 2] = 20.+.02*p[:, 0]
                    decks.append((str(f.ids[i]), sp, p, float(ll[:, 0].mean())))
            layout = roads.projected_ramp_layout(FRAME, [f])
            chunks = roads._deck_chunks(decks, (-1000, -1000, 1000, 1000), FRAME,
                                         layout=layout, sections=roads._join_sections(FRAME, [f]))
            extension = [c for c in chunks if c.get('deck') and c.get('fid') == 'ramp' and not c.get('ctx')]
            self.assertTrue(extension, 'the generated approach has a supported colliding deck')
            guides = [c for c in chunks if c.get('ramp_guidance')]
            self.assertTrue(guides, 'merge guidance continues at deck height')
            for c in extension+guides:
                self.assertTrue(c['fixed'])
                p = np.asarray(c['n'])
                np.testing.assert_allclose(p[:, 2], 20.+.02*p[:, 0], atol=.002)
            # The same bridge spec now preserves the two-lane count and yellow median edge.
            self.assertTrue(any(c['m'] == 'line_yellow' for c in chunks))
            actual=[c for c in chunks if c.get('deck') and not c.get('ctx')]
            context=[c for c in chunks if c.get('ctx')]
            ribbons=list(zip(roadmesh.ribbons(actual),actual))
            cover=roadmesh._parapet_cover(ribbons,list(zip(roadmesh.ribbons(context),context)))
            for (ribbon,c), covered in zip(ribbons,cover):
                if c.get('fid')=='ramp': continue
                # Right edge of the eastbound through deck is now beside the added
                # lane, not an exposed edge allowed to carry a collision barrier.
                right=ribbon[1]
                use=(right[:,0]>right[:,0].min()+10)&(right[:,0]<right[:,0].max()-10)
                self.assertTrue(covered[1][use].all(), 'no parapet between the through and auxiliary lanes')
            mesh=roadmesh.deck(actual,(0.,0.,0.),context=context)
            self.assertIsNotNone(mesh)
            self.assertTrue(np.isfinite(mesh[0]).all())

    def test_unrelated_crossing_bridge_does_not_raise_the_ramp(self):
        f = interchange()
        f.rules['level'] = rules([(0, 1., .1, .2)], 'float')  # well outside the auxiliary approach
        band = roads.projected_ramp_layout(FRAME, [f])[3][0]
        self.assertTrue(all(s is None for s, _ in rampsupport.runs(band['pts'], band['supports'])))

    def test_auxiliary_abutments_share_the_mainline_grading_on_a_hillside(self):
        from test_grading import FakeMD
        from test_roads import LAT,LON,M_LAT
        import mapcells
        f=bridge_exit()
        elev=lambda la,lo: 100.+.2*(np.asarray(la)-LAT)*M_LAT
        g=grading.Grader(FRAME,FakeMD(f),elev)
        plans=g._cell_plans(mapcells.cell_of(LAT,LON))
        auxiliary=[p for fid,p in plans if ':aux' in fid]
        main=[(roads._with_cross(np.c_[p.xy,p.z],{}),p.road_half) for fid,p in plans if fid in ('upstream','before','after')]
        self.assertTrue(auxiliary)
        for p in auxiliary:
            q,half=roads._nearest_road(np.c_[p.xy,p.z],main)
            use=np.linalg.norm(q[:,:2]-p.xy,axis=1)<=half+p.road_half+1.
            np.testing.assert_allclose(p.z[use],q[use,2],atol=1e-6)

    def test_auxiliary_grade_does_not_follow_an_unconnected_overpass(self):
        p=grading.Plan(np.array([[0.,-8.],[100.,-8.]]),np.array([10.,12.]),4.)
        highway=grading.Plan(np.array([[0.,0.],[100.,0.]]),np.array([11.,13.]),6.)
        flyover=grading.Plan(np.array([[50.,-100.],[50.,100.]]),np.array([80.,80.]),6.)
        grading._match_auxiliary_grades([('ramp:aux0',p),('main',highway),('overpass',flyover)],{'ramp':{'main'}})
        np.testing.assert_allclose(p.z,[11.,13.])


if __name__ == '__main__':
    unittest.main()
