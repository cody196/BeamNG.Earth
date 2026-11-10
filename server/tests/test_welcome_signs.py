"""State entries on directed/fragmented roads and the packaged welcome-board pipeline."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'server'))
sys.path.insert(0, str(ROOT))
import geodesy
import cdae
import mapgeom
import signroads
import signstream
import welcomesigns as w
from tools import package


class Frame:
    """An exact local projection keeps metre-scale boundary cases unambiguous."""
    lat0, lon0, h0 = 0., 0., 0.
    def geodetic_to_enu(self, lat, lon, h):
        return np.asarray(lon)*100000, np.asarray(lat)*100000, np.asarray(h)
    def enu_to_geodetic(self, e, n, h):
        return np.asarray(n)/100000, np.asarray(e)/100000, np.asarray(h)


FRAME = Frame()
SPEC = signroads.Spec(12., 'motorway', True, 1., False)


def boundary(left='MI', right='IN'):
    def feature(code, a, b):
        return {'properties':{'STUSAB':code}, 'geometry':{'type':'Polygon','coordinates':[
            [[a,-.02],[b,-.02],[b,.02],[a,.02],[a,-.02]]]}}
    return w.Borders({'features':[feature(left,-.1,0),feature(right,0,.1)]})


def row(fid, coords, spec=SPEC):
    points=np.asarray(coords,float)
    return fid,spec,np.c_[points,points/100000]


def pavement(rows):
    return [(fid,sp,np.c_[line[:,:2],np.zeros(len(line))],sp.width) for fid,sp,line in rows]


class PlacementTest(unittest.TestCase):
    def signs(self, rows, ground=None, index=None):
        return w.plans(FRAME,rows,pavement(rows) if ground is None else ground,index or boundary())

    def test_each_side_welcomes_the_entering_direction_on_right_shoulder(self):
        rows=[row('east',[(-200,0),(200,0)]),row('west',[(200,0),(-200,0)])]
        signs=self.signs(rows)
        self.assertEqual({s['state'] for s in signs},{'MI','IN'})
        for s in signs:
            right=np.array([s['travel'][1],-s['travel'][0]])
            self.assertGreater((s['xy']-s['road_point'])@right,6+w.CLEARANCE_M)
            self.assertEqual(s['state'],'IN' if s['travel'][0]>0 else 'MI')
            self.assertGreater(s['road_point']@s['travel'],0)

    def test_single_oneway_carriageway_does_not_create_outbound_sign(self):
        signs=self.signs([row('oneway',[(-200,0),(200,0)])])
        self.assertEqual([s['state'] for s in signs],['IN'])

    def test_boundary_at_feature_connector_has_exactly_one_board(self):
        rows=[row('a',[(-200,0),(0,0)]),row('b',[(0,0),(200,0)])]
        signs=self.signs(rows)
        self.assertEqual(len(signs),1)
        whole=self.signs([row('whole',[(-200,0),(200,0)])])[0]
        np.testing.assert_allclose(signs[0]['xy'],whole['xy'])
        backwards=self.signs(list(reversed(rows)))
        np.testing.assert_allclose(signs[0]['xy'],backwards[0]['xy'])

    def test_long_feature_ending_at_border_still_follows_continuation(self):
        rows=[row('long',[(-3000,0),(0,0)]),row('after',[(0,0),(3000,0)])]
        signs=self.signs(rows)
        self.assertEqual(len(signs),1)
        self.assertEqual(signs[0]['state'],'IN')

    def test_source_rules_reverse_oneway_and_exclude_ramps_and_minor_roads(self):
        from test_roads import rules
        line=np.array([[-.002,.001],[.002,.001]])
        feats=mapgeom.build('roads',np.array(['main','ramp','footway']),[(mapgeom.LINE,[[line]])]*3)
        feats.attrs={'class':np.array(['motorway','motorway','footway']),'subtype':np.array(['road']*3)}
        feats.rules={'oneway':rules([(0,-1.),(1,1.)],'float'),'subclass':rules([(1,'link')])}
        context=SimpleNamespace(urban=None,widths=None)
        rows=w._rows(FRAME,feats,context,False)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][0],'main')
        self.assertGreater(rows[0][2][0,0],rows[0][2][-1,0])
        self.assertEqual([s['state'] for s in self.signs(rows)],['MI'])

    def test_unmarked_two_way_source_produces_both_directions(self):
        line=np.array([[-.002,.001],[.002,.001]])
        feats=mapgeom.build('roads',np.array(['main']),[(mapgeom.LINE,[[line]])])
        feats.attrs={'class':np.array(['primary']),'subtype':np.array(['road'])}
        rows=w._rows(FRAME,feats,SimpleNamespace(urban=None,widths=None),False)
        self.assertEqual(len(rows),2)
        self.assertEqual({s['state'] for s in self.signs(rows)},{'IN','MI'})

    def test_bridge_crossing_follows_connected_road_to_receiving_bank(self):
        rows=[row('a',[(-500,0),(-100,0)]),row('bridge',[(-100,0),(150,0)]),
              row('b',[(150,0),(500,0)])]
        signs=self.signs(rows,pavement([rows[0],rows[2]]))
        self.assertEqual(len(signs),1)
        self.assertGreaterEqual(signs[0]['road_point'][0],150)

    def test_no_ground_or_no_continuation_means_no_floating_sign(self):
        self.assertEqual(self.signs([row('bridge',[(-200,0),(200,0)])],[]),[])
        self.assertEqual(self.signs([row('end',[(-200,0),(0,0)])]),[])

    def test_parallel_and_tangential_roads_do_not_get_welcome_boards(self):
        for coords in ([(-20,-200),(-20,200)],[(-100,-100),(0,0),(-100,100)]):
            self.assertEqual(self.signs([row('touch',coords)]),[])

    def test_same_state_interior_has_no_board(self):
        self.assertEqual(self.signs([row('inside',[(50,0),(300,0)])]),[])

    def test_two_parallel_incoming_carriageways_remain_distinct(self):
        signs=self.signs([row('one',[(-200,0),(200,0)]),row('two',[(-200,40),(200,40)])])
        self.assertEqual(len(signs),2)

    def test_sign_moves_clear_of_adjacent_road_pavement(self):
        rows=[row('incoming',[(-200,0),(200,0)])]
        other=row('side',[(10,-18),(65,-18)])
        signs=self.signs(rows,pavement(rows+[other]))
        self.assertEqual(len(signs),1)
        self.assertGreater(signs[0]['road_point'][0],65)

    def test_hawaii_and_dc_have_no_state_welcome_design(self):
        for code in ('HI','DC'):
            self.assertEqual(self.signs([row('road',[(-200,0),(200,0)])],index=boundary(right=code)),[])

    def test_international_entry_including_alaska(self):
        index=w.Borders({'features':[{'properties':{'STUSAB':'AK'},'geometry':{
            'type':'Polygon','coordinates':[[[0,-.02],[.1,-.02],[.1,.02],[0,.02],[0,-.02]]]}}]})
        self.assertEqual([s['state'] for s in self.signs([row('alaska',[(-200,0),(200,0)])],index=index)],['AK'])

    def test_real_census_indiana_michigan_boundary(self):
        frame=geodesy.EnuFrame(41.76,-85.0,0.)
        ring=np.array([[-85.,41.75],[-85.,41.77]])
        line=w._line(frame,ring)
        rows=[('north',SPEC,line),('south',SPEC,line[::-1])]
        signs=w.plans(frame,rows,pavement(rows))
        self.assertEqual({s['state'] for s in signs},{'IN','MI'})
        for s in signs:
            self.assertEqual(s['state'],'MI' if s['travel'][1]>0 else 'IN')

    def test_tile_ownership_and_ground_height(self):
        rows=[row('road',[(-200,100),(500,100)])]
        context=SimpleNamespace(around=lambda p:object(),pavements=lambda *a:pavement(rows))
        captures=[]
        def capture(signs, origin):captures.extend(signs);return None
        with mock.patch.object(w,'borders',return_value=boundary()),mock.patch.object(w,'_rows',return_value=rows),\
             mock.patch.object(w,'build',side_effect=capture):
            for tx,ty in ((-1,0),(0,0),(1,0),(0,-1)):
                w.build_tile(FRAME,tx,ty,lambda la,lo:np.full(np.shape(la),30.),context)
        self.assertEqual(len(captures),1)
        self.assertGreater(captures[0]['bottom'],30.)
        np.testing.assert_allclose(captures[0]['bases'],[30.,30.])


class AssetsAndPipelineTest(unittest.TestCase):
    def test_frozen_build_contains_module_and_entire_boundary_and_face_catalog(self):
        from tools import build_app
        import shutil
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build_app.subprocess,'run') as run:
            build_app.pyinstaller(tmp,'icon.ico',True,ver='0.0.0')
            command=run.call_args.args[0]
            self.assertIn('welcomesigns',command)
            data=next(command[i+1].split(build_app.SEP,1) for i,v in enumerate(command[:-1])
                      if v=='--add-data' and command[i+1].split(build_app.SEP,1)[0]==str(ROOT/'server/data'))
            dest=Path(tmp)/'bundle'/data[1];dest.mkdir(parents=True)
            for name in ('welcome_states.geojson.gz','welcome_signs.json'):
                shutil.copyfile(Path(data[0])/name,dest/name)
            with mock.patch.object(w,'DATA',dest):
                w.borders.cache_clear();w.designs.cache_clear()
                try:
                    self.assertEqual(len(w.designs()),49)
                    self.assertEqual(w.borders().states([[-85.,41.75]])[0],'IN')
                finally:
                    w.borders.cache_clear();w.designs.cache_clear()

    def test_all_49_materials_textures_and_server_data_ship(self):
        from PIL import Image
        designs=w.designs()
        self.assertEqual(len(designs),49)
        self.assertIn('AK',designs)
        self.assertNotIn('HI',designs)
        self.assertNotIn('DC',designs)
        files=set(package.collect())
        root='mod/beamng_earth/levels/beamng_earth/art/shapes/beamngEarth/welcome_signs/'
        materials=json.loads((ROOT/root/'main.materials.json').read_text())
        self.assertEqual(len(materials),49)
        for code in designs:
            key='bne_welcome_'+code.lower()
            self.assertIn(root+code.lower()+'.png',files)
            self.assertIn(key,materials)
            with Image.open(ROOT/root/(code.lower()+'.png')) as image:
                self.assertEqual(image.size,(1024,1024))
        for name in ('welcome_signs.json','welcome_states.geojson.gz'):
            self.assertIn('server/data/'+name,files)

    def test_mesh_faces_incoming_traffic_with_valid_materials_and_uvs(self):
        sign=dict(state='IN',centre=np.array([10.,20.,5.]),travel=np.array([0.,1.]),bottom=7.,bases=[5.,5.])
        p,t,uv,mats,mi=w.build([sign],(0,0,0))
        self.assertTrue(np.isfinite(p).all())
        self.assertEqual(len(p),len(uv))
        self.assertLess(t.max(),len(p))
        self.assertLess(mi.max(),len(mats))
        face=t[mi==mats.index('bne_welcome_in')][0]
        normal=np.cross(p[face[1]]-p[face[0]],p[face[2]]-p[face[0]])
        self.assertLess(normal[1],0)
        self.assertEqual(set(map(tuple,uv[t[mi==mats.index('bne_welcome_in')]].reshape(-1,2))),
                         {(0,0),(1,0),(1,1),(0,1)})

    def test_shaped_plates_preserve_contour_area_and_triangle_winding(self):
        for code in ('MD', 'WI'):
            for panel in w.designs()[code]['panels']:
                points=np.asarray(panel['points']);tri=np.asarray(panel['triangles'])
                self.assertEqual(len(tri),len(points)-2)
                polygon_area=np.sum(points[:,0]*np.roll(points[:,1],-1)-points[:,1]*np.roll(points[:,0],-1))/2
                a=points[tri[:,1]]-points[tri[:,0]];b=points[tri[:,2]]-points[tri[:,0]]
                areas=(a[:,0]*b[:,1]-a[:,1]*b[:,0])/2
                self.assertTrue((areas>0).all(),code)
                self.assertAlmostEqual(float(areas.sum()),float(polygon_area),places=6)

    def test_cutout_mesh_faces_traffic_and_uses_global_texture_coordinates(self):
        for code in ('MD','WI'):
            style=w.designs()[code];width,height=style['width'],style['height']
            sign=dict(state=code,centre=np.zeros(3),travel=np.array([0.,1.]),bottom=2.,bases=[0.,0.])
            p,t,uv,mats,mi=w.build([sign],(0,0,0))
            faces=t[mi==mats.index('bne_welcome_'+code.lower())]
            normals=np.cross(p[faces[:,1]]-p[faces[:,0]],p[faces[:,2]]-p[faces[:,0]])
            self.assertTrue((normals[:,1]<0).all())
            indices=np.unique(faces)
            np.testing.assert_allclose(uv[indices,0],p[indices,0]/width+.5,atol=1e-6)
            np.testing.assert_allclose(uv[indices,1],(p[indices,2]-2)/height,atol=1e-6)
            self.assertTrue(((uv[indices]>=0)&(uv[indices]<=1)).all())
            self.assertTrue(np.isfinite(p).all())

    def test_exported_faces_map_image_top_to_board_top_for_all_states(self):
        # Exercise the actual signstream -> roadmesh -> CDAE path. Checking
        # pre-export UV corners alone missed the writer's Collada V conversion.
        directions=((0.,1.),(1.,0.),(0.,-1.),(-1.,0.))
        with tempfile.TemporaryDirectory() as tmp:
            for i,(code,style) in enumerate(w.designs().items()):
                with self.subTest(state=code):
                    travel=np.array(directions[i % len(directions)])
                    centre=np.array([10.,20.,5.]);bottom=7.
                    sign=dict(state=code,centre=centre,travel=travel,bottom=bottom,bases=[5.,5.])
                    path,_=signstream.write_tile(tmp,'/temp/test',i+1,0,0,
                                                (None,None,None,None,None,w.build([sign],(0,0,0))))
                    doc=json.loads((Path(tmp)/Path(path).name).read_text())
                    shape=cdae.read(Path(tmp)/Path(doc['welcomes']['shape']).name)
                    mat=next(j for j,m in enumerate(shape['materials']) if m['name']=='bne_welcome_'+code.lower())
                    arrays=cdae.mesh_arrays(shape['meshes'][0])
                    indices=[]
                    for start,count,flags in arrays['primitives']:
                        if flags & cdae.PRIM_MATERIAL_MASK == mat:
                            indices.extend(arrays['indices'][start:start+count])
                    used=np.unique(indices)
                    self.assertGreater(len(used),0)
                    points=arrays['verts'][used];uv=arrays['tverts'][used]
                    right=np.array([travel[1],-travel[0]])
                    expected_u=(points[:,:2]-centre[:2]) @ right / style['width']+.5
                    # Stored BeamNG UVs index the PNG from its top left:
                    # high vertices sample the top rows, not the bottom rows.
                    image_row=1-(points[:,2]-bottom)/style['height']
                    np.testing.assert_allclose(uv[:,0],expected_u,atol=2e-6)
                    np.testing.assert_allclose(uv[:,1],image_row,atol=2e-6)
                    self.assertTrue((arrays['norms'][used,:2] @ travel < -.99).all())

    def test_arched_plate_does_not_fill_top_corners_or_extend_poles_above_it(self):
        style=w.designs()['MD'];panel=style['panels'][0]
        points=np.asarray(panel['points'])
        self.assertLess(points[points[:,0]<.1,1].max(),.7)
        self.assertGreater(points[:,1].max(),.98)
        for x in (.16,.84):
            self.assertLess(w._post_top(style,x),1.)
            self.assertGreater(w._post_top(style,x),.65)

    def test_design_sources_and_public_domain_emblem_notices_ship(self):
        root=ROOT/'mod/beamng_earth/levels/beamng_earth/art/shapes/beamngEarth/welcome_signs'
        sources=json.loads((root/'sources.json').read_text())['states']
        self.assertEqual(set(sources),set(w.designs()))
        for code,s in sources.items():
            self.assertTrue(s['edition'])
            self.assertTrue(s['references'][0].startswith('https://'))
            self.assertNotEqual(s['references'][0],'https://commons.wikimedia.org/wiki/U.S._state_welcome_signs')
        self.assertTrue((root/'Lora-LICENSE.txt').is_file())
        self.assertIn('Xrmap',(root/'NOTICE.md').read_text())

    def test_welcome_mesh_written_as_own_optional_sign_kind(self):
        sign=dict(state='IN',centre=np.array([10.,20.,0.]),travel=np.array([0.,1.]),bottom=2.,bases=[0.,0.])
        with tempfile.TemporaryDirectory() as tmp:
            path,n=signstream.write_tile(tmp,'/temp/test',1,0,0,(None,None,None,None,None,w.build([sign],(0,0,0))))
            doc=json.loads((Path(tmp)/Path(path).name).read_text())
            self.assertEqual(n,1)
            self.assertEqual(doc['chunks'],[])
            self.assertTrue((Path(tmp)/'welcomes_1_0_0.cdae').is_file())
            self.assertIn('welcomes',doc)

    def test_optional_failure_does_not_remove_existing_signs_or_roads(self):
        with mock.patch.object(w,'build_tile',side_effect=ValueError('fixture failure')),mock.patch.object(signstream.log,'warning'):
            self.assertIsNone(signstream._welcomes(None,0,0,None,None,[],False))


if __name__=='__main__':unittest.main()
