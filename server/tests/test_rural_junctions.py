"""Country junctions must not inherit urban curbs from their own paved pixels."""
import math
import sys
from pathlib import Path
import unittest
import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import roads
import junctions
from test_roads import features, rules, FRAME, flat, LAT, LON, M_LAT, M_LON


def crossroads():
    centre = (120., 120.)
    return features([[centre, (400,120)], [centre, (120,400)],
                     [centre, (-160,120)], [centre, (120,-160)]], ['tertiary']*4)


def road_pixels(lat, lon):
    x, y = (lon-LON)*M_LON, (lat-LAT)*M_LAT
    return (np.abs(x-120)<6) | (np.abs(y-120)<6)


class RuralJunctionTest(unittest.TestCase):
    def test_paved_country_crossroads_stays_rural_and_flat(self):
        f = crossroads()
        self.assertTrue(road_pixels(f.lonlat[:,1],f.lonlat[:,0]).all())
        specs = roads.road_specs(f, road_pixels)
        self.assertFalse(any(s.urban or roads.has_sidewalks(s) for s in specs))
        walks = []
        chunks = roads.build_tile(FRAME,0,0,[f],flat,road_pixels,walks=walks)
        self.assertEqual(walks, [])
        self.assertFalse(any(c['m']==junctions.CROSSWALK['m'] for c in chunks))
        corners=roads.ground_corners(FRAME,[f],road_pixels)
        self.assertEqual(len(corners),4, 'flat rounded pavement at all four corners')
        self.assertTrue(all(c.get('paved_only') for c in corners))
        self.assertTrue(any(c['m']=='line_yellow' for c in chunks))

    def test_dense_junction_vertices_do_not_outvote_open_fields(self):
        points=[(x,0) for x in np.r_[np.linspace(0,5,100),500,1000]]
        f=features([points],['residential'])
        def cover(lat,lon):
            return (lon-LON)*M_LON < 12
        self.assertFalse(roads.road_specs(f,cover)[0].urban)

    def test_town_junction_keeps_its_walks_and_crossings(self):
        f=crossroads()
        urban=lambda la,lo: np.ones(np.shape(la),bool)
        walks=[]
        chunks=roads.build_tile(FRAME,0,0,[f],flat,urban,walks=walks)
        self.assertEqual(len([w for w in walks if 'corner' in w]),4)
        self.assertEqual(len([c for c in chunks if c['m']==junctions.CROSSWALK['m']]),4)

    def test_mapped_absence_overrides_urban_guess_and_mapped_presence_survives(self):
        for tag in ('no','none','separate'):
            f=crossroads();f.attrs['osm_sidewalk']=np.array([tag]*4)
            specs=roads.road_specs(f,lambda la,lo:np.ones(np.shape(la),bool))
            self.assertFalse(any(roads.has_sidewalks(s) for s in specs))
        f=crossroads();f.attrs['osm_sidewalk']=np.array(['both']*4)
        specs=roads.road_specs(f,road_pixels)
        self.assertTrue(all(roads.has_sidewalks(s) for s in specs))

    def test_rural_triangle_has_no_invented_concrete_island(self):
        f=features([[(70,70),(130,70)],[(130,70),(100,110)],[(100,110),(70,70)]],['tertiary']*3)
        f.rules['oneway']=rules([(i,1.) for i in range(3)],'float')
        walks=[]
        roads.build_tile(FRAME,0,0,[f],flat,walks=walks)
        self.assertEqual(walks,[])

    def test_rural_roundabout_keeps_its_island(self):
        t=np.linspace(0,2*math.pi,49)
        ring=np.c_[120+16*np.cos(t),120+16*np.sin(t)]
        f=features([ring[:25],ring[24:]],['tertiary']*2)
        f.rules['oneway']=rules([(0,1.),(1,1.)],'float')
        walks=[]
        roads.build_tile(FRAME,0,0,[f],flat,walks=walks)
        self.assertTrue(any(w.get('fid')=='island' for w in walks))


if __name__=='__main__':
    unittest.main()
