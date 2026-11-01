import unittest,math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from spatial_geometry import triangle_distance,BVH,check_pairs

class SpatialTests(unittest.TestCase):
 def test_parallel_faces_have_exact_normal_distance(self):
  a=[(0,0,0),(4,0,0),(0,4,0)];b=[(1,1,.006),(2,1,.006),(1,2,.006)]
  d,p,q,cross=triangle_distance(a,b);self.assertAlmostEqual(math.sqrt(d),.006,12);self.assertFalse(cross)
 def test_crossing_edges_hit_triangle_interior(self):
  a=[(-2,-2,0),(2,-2,0),(0,2,0)];b=[(0,0,-1),(0,0,1),(2,0,1)]
  self.assertEqual(triangle_distance(a,b)[0],0)
 def test_coplanar_containment_is_zero_not_centroid_distance(self):
  a=[(0,0,0),(6,0,0),(0,6,0)];b=[(1,1,0),(2,1,0),(1,2,0)]
  self.assertAlmostEqual(triangle_distance(a,b)[0],0)
 def test_closest_points_can_be_inside_edges(self):
  a=[(-2,0,0),(2,0,0),(0,-.01,0)];b=[(0,-2,.02),(0,2,.02),(.01,0,.02)]
  self.assertAlmostEqual(math.sqrt(triangle_distance(a,b)[0]),.02,10)
 def test_limit_is_explicit_and_not_passed(self):
  a=BVH([[(0,0,0),(1,0,0),(0,1,0)]]);b=BVH([[(0,0,1),(1,0,1),(0,1,1)]])
  r=a.nearest(b,max_tests=0);self.assertFalse(r['complete']);self.assertIsNone(r['distanceFt'])
 def test_closed_tetrahedron_contains_inner_probe(self):
  a,b,c,d=(0,0,0),(3,0,0),(0,3,0),(0,0,3)
  mesh=BVH([(a,c,b),(a,b,d),(a,d,c),(b,c,d)])
  self.assertTrue(mesh.contains((.2,.2,.2)));self.assertFalse(mesh.contains((2,2,2)))
 def test_disconnected_enclosed_body_is_rejected(self):
  outer=[(0,0,0),(3,0,0),(0,3,0),(0,0,3)];inner=[(.2,.2,.2),(.4,.2,.2),(.2,.4,.2),(.2,.2,.4)]
  f=[[0,2,1],[0,1,3],[0,3,2],[1,2,3]];mesh={'nodes':outer+inner,'faces':f+[[v+4 for v in q]for q in f],'faceParts':[1]*4+[2]*4,'parts':{1:{'geomId':'A'},2:{'geomId':'B'}}}
  r=check_pairs(mesh,[{'a':'A','b':'B','minimumGapFt':.001,'toleranceFt':.0001}],{'A':'Outer','B':'Inner'})[0]
  self.assertTrue(r['contained']);self.assertFalse(r['passed']);self.assertEqual(r['state'],'overlap')

if __name__=='__main__':unittest.main()
