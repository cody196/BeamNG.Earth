"""Shared curved geometry preserves rule locations and never edits raw maps."""
import unittest
import numpy as np
import roadcurves
import roads
from test_roads import features, rules, FRAME


class CurvesTest(unittest.TestCase):
    def test_tangents_are_smooth_and_displacement_bounded(self):
        original=np.array([[0.,0.],[100.,0.],[200.,45.],[270.,110.]])
        p,old,new=roadcurves.rounded(original)
        self.assertGreater(len(p),30)
        np.testing.assert_array_equal(p[[0,-1]],original[[0,-1]])
        v=np.diff(p,axis=0); v/=np.linalg.norm(v,axis=1)[:,None]
        turns=np.degrees(np.arccos(np.clip((v[:-1]*v[1:]).sum(1),-1,1)))
        self.assertLess(turns.max(),4.)
        for q in p:
            d=np.diff(original,axis=0)
            t=np.clip(((q-original[:-1])*d).sum(1)/(d*d).sum(1),0,1)
            self.assertLessEqual(np.linalg.norm(q-(original[:-1]+t[:,None]*d),axis=1).min(),roadcurves.MAX_DEVIATION+.001)
        self.assertTrue((np.diff(old)>0).all() and (np.diff(new)>0).all())

    def test_rules_junctions_and_bridge_ends_keep_locations(self):
        f=features([[(0,0),(100,0),(200,45),(300,50)],[(200,45),(200,140)]],['motorway','secondary'])
        f.rules['flags']=rules([(0,'is_bridge',.15,.65)])
        line=f.parts(0)[0][0]
        scale=np.array([111320*np.cos(np.radians(line[:,1].mean())),110574.])
        lengths=np.linalg.norm(np.diff(line,axis=0)*scale,axis=1)
        join=float(lengths[:2].sum()/lengths.sum())
        f.rules['connectors']=rules([(0,'join',join,join),(1,'join',0.,0.)])
        before=f.lonlat.copy()
        prepared=roadcurves.prepare(f)
        np.testing.assert_array_equal(f.lonlat,before)
        self.assertIs(roadcurves.prepare(prepared),prepared)
        self.assertGreater(len(prepared.lonlat),len(f.lonlat))
        for original,curved in zip(roads.raw_level_ranges(f,0),roads.raw_level_ranges(prepared,0)):
            # Test rule station positions directly, in the same local metric as preparation.
            scale=np.array([111320*np.cos(np.radians(f.parts(0)[0][0][:,1].mean())),110574.])
            def at(g,fraction):
                p=g.parts(0)[0][0]*scale
                s=np.r_[0,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))]
                return np.array([np.interp(fraction*s[-1],s,p[:,k]) for k in (0,1)])
            for r,c in zip(original[:2],curved[:2]):
                np.testing.assert_allclose(at(f,r),at(prepared,c),atol=.001)
        shared=f.parts(1)[0][0][0]
        self.assertLess(np.linalg.norm(prepared.parts(0)[0][0]-shared,axis=1).min(),1e-9)

    def test_curve_is_independent_of_neighbour_cell_contents(self):
        line=[(0,0),(100,0),(200,45),(300,50)]
        a=features([line],['motorway'])
        b=features([line,[(100,0),(100,100)]],['motorway','secondary'])
        np.testing.assert_array_equal(roadcurves.prepare(a).parts(0)[0][0],
                                      roadcurves.prepare(b).parts(0)[0][0])

    def test_straight_duplicate_and_hard_corners_are_safe(self):
        for p in (np.array([[0.,0.],[0.,0.],[100.,0.]]),np.array([[0.,0.],[10.,0.],[0.,1.]])):
            q,_,_=roadcurves.rounded(p)
            self.assertTrue(np.isfinite(q).all())
            np.testing.assert_array_equal(q[[0,-1]],p[[0,-1]])
