"""Measure the migrated paint, route signs and curve geometry at their consumers."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'server'))
sys.path.insert(0, str(ROOT))
import geodesy
import grading
import highwaysigns
import legacyshields
import markings
import milemarkers
import milemounts
import roadcurves
import roadmarkings
import roadmesh
import roads
import railtags
import routeindex
import routemarkers
import signroads
from tools import build_sign_tags
from test_roads import features, rules, FRAME


class PaintDimensionsTest(unittest.TestCase):
    # Independent expected measurements transcribed from ROAD_IMPROVEMENT_NOTES.md.
    PROFILES = {'': ((3., 8., .35), (1.2, 2.8, .35), .35),
                'MI': ((4.5, 11.5, .4), (1.5, 6., .35), .4),
                'MN': ((3.1, 12.25, .3), None, .45),
                'WI': ((5.15, 10.25, .31), (1.25, 2.9, .3), .32),
                'CA': ((4.6, 10.5, .35), (2.3, 4.9, .25), .25),
                'KY': ((3.5, 8.2, .3), None, .3)}

    def test_measure_rendered_dashes_gaps_and_solids_for_every_profile(self):
        line = np.array([[0., 0., 8.], [200., 0., 12.]])
        for state, (travel, ramp, solid) in self.PROFILES.items():
            for link in (False, True):
                for direction in (-1, 1):
                    with self.subTest(state=state, link=link, direction=direction):
                        sp = roads.Spec(12., 'paved', False, 'motorway', True,
                                        dir=direction, lanes=2, link=link, state=state)
                        result = roads.extras(sp, line, -85., country='US')
                        lanes = [(w, p) for lk, w, p in result if lk.get('kind') == 'lane']
                        expected = ramp if link else travel
                        if expected is None:
                            self.assertEqual(lanes, [])
                        else:
                            length, gap, width = expected
                            self.assertGreater(len(lanes), 5)
                            self.assertAlmostEqual(lanes[0][0], width)
                            self.assertAlmostEqual(lanes[0][1][-1, 0]-lanes[0][1][0, 0], length)
                            self.assertAlmostEqual(lanes[1][1][0, 0]-lanes[0][1][-1, 0], gap)
                            chunk = dict(m='line_white', w=width, n=lanes[0][1], fixed=True)
                            left, right, _, _, _, z = roadmesh.ribbons([chunk])[0]
                            np.testing.assert_allclose(np.linalg.norm(left-right, axis=1), width)
                            self.assertAlmostEqual(z[0], 8.)
                        edges = [(lk, w, p) for lk, w, p in result if lk.get('kind') == 'edge']
                        self.assertEqual(len(edges), 2)
                        for lk, width, path in edges:
                            self.assertEqual(width, solid)
                            self.assertEqual(lk['m'], 'line_yellow' if path[0, 1]*direction > 0 else 'line_white')

    def test_no_change_lane_marking_uses_solid_not_dashed_width(self):
        sp = roads.Spec(12., 'paved', False, 'motorway', True, lanes=2, state='MN')
        result = roads.extras(sp, np.array([[0.,0.,0.], [100.,0.,0.]]), -93.,
                              country='US', osm={'change:lanes': 'no|no'})
        lane, = [(w, p) for lk, w, p in result if lk.get('kind') == 'lane']
        self.assertEqual(lane[0], .45)
        self.assertEqual(lane[1][-1, 0], 100.)

    def test_state_profile_is_shared_by_ground_bridge_and_tunnel_specs(self):
        for flag, get in (('is_bridge', roads.bridge_specs), ('is_tunnel', roads.tunnel_specs)):
            f = features([[(0,0),(150,30),(300,30)]], ['motorway'])
            f.lonlat[:] += [-84.55-f.lonlat[0,0], 42.73-f.lonlat[0,1]]
            f.rules['flags'] = rules([(0, flag, .2, .8)])
            sp = get(f)[0]
            self.assertIsNotNone(sp)
            self.assertEqual(sp.state, 'MI')
        self.assertEqual(roads.road_specs(f)[0].state, 'MI')

    def test_explicit_non_us_country_keeps_its_dimensions(self):
        self.assertEqual(markings.style('DE', 8., 'MI'), markings.STYLES['DE'])
        self.assertEqual(markings.style('CA', -90.), markings.STYLES['CA'])


class CurvedConsumerTest(unittest.TestCase):
    def test_gentle_bends_survive_mesh_generation(self):
        raw = np.array([[0.,0.],[150.,0.],[300.,3.],[450.,10.],[600.,20.]])
        q, _, _ = roadcurves.rounded(raw)
        line = np.c_[q, np.zeros(len(q))]
        sp = roads.Spec(14., 'paved', False, 'motorway', True, dir=1, lanes=2)
        for _, width, path in roads.extras(sp, line, -100.):
            for part in roads.split(roads.densify(roads.simplify(path))):
                left, right, *_ = roadmesh.ribbons([dict(n=part, w=width, m='line_white')])[0]
                d = np.diff((left+right)/2, axis=0)
                angle = np.unwrap(np.arctan2(d[:,1], d[:,0]))
                self.assertLess(np.degrees(np.abs(np.diff(angle))).max(initial=0), .45)

    def test_curved_physics_keeps_smooth_bank_and_level_bridge_ends(self):
        raw = np.array([[0.,0.],[150.,0.],[300.,50.],[450.,50.],[600.,0.]])
        curve, _, _ = roadcurves.rounded(raw)
        xy, _ = grading.resample(curve, 2.)
        sp = roads.Spec(14., 'paved', False, 'motorway')
        plan = grading._plan(xy, np.zeros(len(xy)), sp, abut=(True, True))
        self.assertLessEqual(np.linalg.norm(np.diff(plan.xy, axis=0), axis=1).max(), 4.01)
        bank = plan.bank
        self.assertEqual(bank[0], 0.)
        self.assertEqual(bank[-1], 0.)
        self.assertLessEqual(np.abs(bank).max(), .08)
        self.assertLess(np.abs(np.diff(np.degrees(np.arctan(bank)))).max(), .48)


class RestoredSignsTest(unittest.TestCase):
    def test_bundled_markers_survive_missing_weekly_data(self):
        frame = geodesy.EnuFrame(42.82, -84.27)
        source = highwaysigns.Source(SimpleNamespace(cache_dir='unused'), tags=Mock())
        source.tags.query.side_effect = OSError('offline')
        found = source.objects(frame, (-20000,-20000,20000,20000))
        self.assertTrue(found)
        self.assertTrue(all(o['mile_marker']['source'].startswith('dot:') for o in found))
        objects, _ = milemarkers.references()
        self.assertTrue(any(o['mile_marker']['mile'] % 1 for o in objects))

    def test_cached_route_shields_are_read_only_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'mapdata/raw/osm-lanes'
            root.mkdir(parents=True)
            for name in ('first', 'overlap'):
                with sqlite3.connect(root/(name+'.signs.v3.sqlite')) as con:
                    con.execute('CREATE TABLE objects(id INTEGER,lon REAL,lat REAL,ways TEXT,kind TEXT)')
                    con.execute('CREATE VIRTUAL TABLE spatial USING rtree(id,minlon,maxlon,minlat,maxlat)')
                    con.execute('INSERT INTO objects VALUES(1,-84,43,?,?)',
                                (json.dumps([dict(type='shield', routes=[dict(kind='interstate', number='69')])]), 'roadside'))
                    con.execute('INSERT INTO spatial VALUES(1,-84,-84,43,43)')
                con.close()
            before = {p.name:p.read_bytes() for p in root.iterdir()}
            found = legacyshields.Source(tmp).query(-85,42,-83,44)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]['roadside']['routes'][0]['number'], '69')
            self.assertEqual(before, {p.name:p.read_bytes() for p in root.iterdir()})

    def test_route_chain_spacing_directions_and_generated_mesh(self):
        frame = geodesy.EnuFrame(42.82,-84.27)
        xy = np.array([[0.,0.],[2500.,0.],[5000.,0.],[8000.,0.]])
        lat, lon, _ = frame.enu_to_geodetic(xy[:,0],xy[:,1],0.)
        coords = dict(enumerate(zip(lon,lat)))
        tags = dict(highway='primary', ref='US 127;I 69', oneway='yes')
        ways = [(10,[0,1],tags),(11,[1,2],tags),(12,[2,3],tags)]
        relations = {w:[dict(network='US:I',ref='69',direction='east',role='forward')] for w,_,_ in ways}
        found = routeindex.index_records(ways,coords,relations)
        self.assertEqual(len(found),2)
        self.assertTrue(all(o['ways'][0]['routes'][0]['direction']=='EAST' for o in found))
        points = np.array([[o['lon'],o['lat']] for o in found])
        dist = np.linalg.norm(np.diff(points,axis=0)*[111320*np.cos(np.radians(42.82)),111320])
        self.assertAlmostEqual(dist,routeindex.SHIELD_SPACING,delta=1.)
        obj = found[0];obj['roadside']=obj['ways'][0]
        spec = roads.Spec(10.,'paved',False,'primary',True,dir=1,lanes=2)
        p = np.column_stack(frame.geodetic_to_enu(lat,lon,0.))
        rows = [(f"osm:w{obj['roadside']['main_id']}:f",signroads.spec(spec),p,10.)]
        placed = routemarkers.place(frame,obj,rows,(-100,-100,9000,100),lambda a,b:np.zeros_like(a))
        self.assertIsNotNone(placed)
        mesh = routemarkers.build([placed],(0,0,0))
        self.assertIsNotNone(mesh)
        self.assertTrue(np.isfinite(mesh[0]).all())
        self.assertEqual(set(r['kind'] for r in placed['routes']), {'interstate','us'})
        places = build_sign_tags.Places(np.arange(4),np.asarray(lon),np.asarray(lat))
        shards = build_sign_tags.shields([(w,np.array(r),t) for w,r,t in ways],relations,places)
        self.assertEqual(len(shards),2)
        self.assertTrue(all(r['k']=='shield' for r in shards))
        with tempfile.TemporaryDirectory() as tmp:
            build_sign_tags.write(tmp, shards, {'shields': len(shards)})
            decoded = railtags.SignTags(tmp, None, local=tmp).query(-85.,42.,-83.,44.)
            self.assertEqual(len(decoded), 2)
            self.assertTrue(all(o['roadside']['type'] == 'shield' for o in decoded))
        md = SimpleNamespace(highway_signs=Mock())
        md.highway_signs.context.return_value.pavements.return_value = rows
        x, y, _ = frame.geodetic_to_enu(obj['lat'], obj['lon'], 0.)
        with patch('highwaysigns.tile_objects', return_value=[obj]):
            mesh, miles = highwaysigns.build_tile(md, frame, int(x // roads.TILE), -1,
                                                 lambda a,b:np.zeros_like(a))
        self.assertIsNotNone(mesh)
        self.assertIsNone(miles)

    def test_shard_builder_keeps_primary_us_route_relations(self):
        import importlib.util
        if importlib.util.find_spec('osmium') is None:
            self.skipTest('optional offline PBF builder dependency')
        xml = '''<osm version="0.6">
          <node id="1" lat="42.82" lon="-84.27"/>
          <node id="2" lat="42.82" lon="-84.17"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="primary"/></way>
          <relation id="20"><member type="way" ref="10" role="forward"/>
            <tag k="route" v="road"/><tag k="network" v="US:US"/>
            <tag k="ref" v="127"/><tag k="direction" v="north"/></relation></osm>'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'routes.osm'
            path.write_text(xml, encoding='utf-8')
            *_, ways, relations = build_sign_tags._first_pass(str(path), include_shields=True)
        self.assertEqual([w[0] for w in ways], [10])
        self.assertEqual(routeindex.route_refs(ways[0][2], relations[10]), [('US','127')])

    def test_fractional_marker_mount_requires_current_concrete_barrier(self):
        frame = geodesy.EnuFrame(37.,-85.)
        obj = milemarkers._object('KY',65,12.2,'N',[-85.,37.],[0.,1.],'dot:ky')
        with patch('medians.modules',return_value=np.zeros((0,11))):
            self.assertIsNone(milemounts.mount(frame,obj,[],lambda a,b:np.zeros_like(a)))
        module = np.array([[1,0,0,-1.5,0,1.5,1,0,0,np.nan,np.nan]])
        with patch('medians.modules',return_value=module):
            centre, travel = milemounts.mount(frame,obj,[],lambda a,b:np.zeros_like(a))
        np.testing.assert_allclose(centre,[0.,0.,.88],atol=1e-6)
        np.testing.assert_allclose(travel,[0.,1.])

    def test_blue_markers_use_the_native_median_and_have_one_owner(self):
        frame = geodesy.EnuFrame(37.,-85.)
        spec = roads.Spec(14., 'paved', False, 'motorway', True, dir=1, lanes=3)
        rows = [('north', signroads.spec(spec), np.array([[9.,-600.,0.],[9.,600.,0.]]),14.),
                ('south', signroads.spec(spec._replace(dir=-1)),
                 np.array([[-9.,-600.,0.],[-9.,600.,0.]]),14.)]
        objects = [milemarkers._object('KY',65,12.2,d,[-85.,37.],axis,'dot:ky')
                   for d,axis in [('N',[0.,1.]),('S',[0.,-1.])]]
        placed = milemarkers.place(frame, objects, rows, (-100.,-100.,100.,100.),
                                   lambda a,b:np.zeros_like(a))
        self.assertEqual(len(placed),1)
        self.assertEqual(placed[0]['style'],'ky_blue')
        self.assertTrue(placed[0]['double_sided'])
        self.assertIsNotNone(milemarkers.build(placed,(0,0,0)))


if __name__ == '__main__':
    unittest.main()
