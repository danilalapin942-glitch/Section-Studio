import copy,json,math,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from geometry_frames import matrix,world,local,frame_of,section_plane
from native_projection import anchor_map
from spatial_geometry import BVH,distance_field,check_pairs
from surface_tools import branches,read_semantics,smoothness
from native_control import context,run_cancelable
from job_manager import Jobs
from setup_checks import discover_executables
from assembly_repair import change_surface,control_bound,repair_assembly
from section_studio_server import geoms

def fixture_xml(symmetry=0):
 root=ET.Element('Vsp_Geometry');vehicle=ET.SubElement(root,'Vehicle')
 for gid,center in [('A',3),('B',8)]:
  g=ET.SubElement(vehicle,'Geom');pc=ET.SubElement(g,'ParmContainer');ET.SubElement(pc,'ID').text=gid;ET.SubElement(pc,'Name').text=gid;design=ET.SubElement(pc,'Design');ET.SubElement(design,'Length',Value='10');ET.SubElement(design,'OrderPolicy',Value='0');xf=ET.SubElement(pc,'XForm')
  for k in ['X_Location','Y_Location','Z_Location','Origin']:ET.SubElement(xf,k,Value='0')
  sym=ET.SubElement(pc,'Sym');ET.SubElement(sym,'Sym_Planar_Flag',Value=str(symmetry if gid=='A'else 0));gb=ET.SubElement(g,'GeomBase');ET.SubElement(gb,'TypeName').text='Fuselage';surf=ET.SubElement(ET.SubElement(g,'FuselageGeom'),'XSecSurf')
  for i in range(3):
   xs=ET.SubElement(surf,'XSec');xp=ET.SubElement(xs,'ParmContainer');ET.SubElement(xp,'ID').text=gid+str(i);group=ET.SubElement(xp,'XSec')
   for k,v in [('XLocPercent',i/2),('YLocPercent',center/10),('ZLocPercent',0)]:ET.SubElement(group,k,Value=str(v))
   cv=ET.SubElement(ET.SubElement(xs,'XSec'),'XSecCurve');cp=ET.SubElement(cv,'ParmContainer');c=ET.SubElement(cp,'XSecCurve');ET.SubElement(c,'Width',Value='2');ET.SubElement(c,'Height',Value='2');ET.SubElement(ET.SubElement(cv,'XSecCurve'),'Type').text='2'
 return ET.tostring(root,encoding='unicode')

def pair_fixture():return {'a':'A','b':'B','pointA':(5,4,0),'pointB':(5,4.001,0),'normalA':(0,1,0),'normalB':(0,-1,0),'minimumGapFt':.01,'toleranceFt':.0001,'distanceFt':.001,'state':'below-limit','complete':True,'passed':False}

class FrameTests(unittest.TestCase):
 def test_component_pivot_is_world_position_of_native_center(self):
  f={'origin':[10,20,30],'rotation':[0,90,0],'center':2,'length':10}
  self.assertLess(math.dist(world(f,(2,0,0)),(10,20,30)),1e-12);self.assertLess(math.dist(world(f,(4,0,0)),(10,20,28)),1e-12)
 def test_arbitrary_three_axis_frame_roundtrip(self):
  f={'origin':[12,-5,8],'rotation':[12,17,26],'center':4}
  for p in [(0,0,0),(20,3,-2),(-5,10,12)]:self.assertLess(math.dist(local(f,world(f,p)),p),1e-12)
 def test_section_plane_includes_component_and_section_rotations(self):
  root=ET.fromstring(fixture_xml());g=root.find('./Vehicle/Geom');g.find('ParmContainer/XForm/Origin').set('Value','.25');xs=g.find('FuselageGeom/XSecSurf/XSec');ET.SubElement(xs.find('ParmContainer/XSec'),'ZRotate',Value='90');f=frame_of(g,1);plane=section_plane(xs,f)
  self.assertAlmostEqual(plane['center'][0],-2.5);self.assertLess(math.dist(plane['normal'],(0,1,0)),1e-12)
 def test_relative_parameters_override_stale_absolute_cache(self):
  g=ET.fromstring(fixture_xml()).find('./Vehicle/Geom');xf=g.find('ParmContainer/XForm');xf.find('Origin').set('Value','.25');xf.find('X_Location').set('Value','99');ET.SubElement(xf,'Abs_Or_Relitive_flag',Value='1');ET.SubElement(xf,'X_Rel_Location',Value='3');ET.SubElement(xf,'Y_Rel_Rotation',Value='30');f=frame_of(g,1);self.assertEqual(f['origin'][0],5.5);self.assertEqual(f['rotation'][1],30);self.assertLess(math.dist(world(f,(2.5,0,0)),(5.5,0,0)),1e-12)

class CorrespondenceTests(unittest.TestCase):
 def test_shared_ids_preserve_native_cap_parameter_fraction(self):
  a=[{'id':s}for s in ['a','b','c']];b=[{'id':s}for s in ['a','new','b','c']];layout={'verified':True,'frontCaps':1,'backCaps':1};m=anchor_map(a,b,layout,layout)
  self.assertIn((.25,.2),m);self.assertIn((.5,.6),m);self.assertIn((.75,.8),m);self.assertEqual(m[0],(0,0));self.assertEqual(m[-1],(1,1))
 def test_missing_ids_have_explicit_fallback_guess(self):self.assertEqual(anchor_map([{'id':'a'}],[{'id':'b'}]),[(0,0),(1,1)])

class FieldTests(unittest.TestCase):
 def mesh(self,z=.006):return {'nodes':[(0,0,0),(1,0,0),(0,1,0),(0,0,z),(1,0,z),(0,1,z)],'faces':[[0,1,2],[3,4,5]],'faceParts':[1,2],'parts':{1:{'geomId':'A'},2:{'geomId':'B'}}}
 def pair(self):return [{'a':'A','b':'B','minimumGapFt':.01,'toleranceFt':.0001}]
 def test_centroid_field_has_real_distance_inside_band(self):
  r=distance_field(self.mesh(),self.pair());self.assertTrue(r['complete']);self.assertAlmostEqual(r['faces']['0']['distanceFt'],.006);self.assertFalse(r['faces']['0']['atLeast'])
 def test_outside_band_is_a_lower_bound_not_a_fabricated_distance(self):
  r=distance_field(self.mesh(3),self.pair());self.assertTrue(r['faces']['0']['atLeast']);self.assertAlmostEqual(r['faces']['0']['distanceFt'],.1)
 def test_incomplete_map_does_not_claim_coverage(self):
  r=distance_field(self.mesh(),self.pair(),max_tests=0);self.assertFalse(r['complete']);self.assertEqual(r['visitedFaces'],0)
 def test_nearest_query_honors_cancellation(self):
  tree=BVH([[(0,0,0),(1,0,0),(0,1,0)]]);context.cancel=threading.Event();context.cancel.set()
  try:
   with self.assertRaises(InterruptedError):tree.nearest_point((.2,.2,1))
  finally:context.cancel=None

class SemanticTests(unittest.TestCase):
 def build(self,p,bad=False):
  sections=[{'id':'s'+str(i),'center':(i,0,0),'normal':(1,0,0),'localX':i}for i in range(3)];meta={'A':{'name':'Body','type':'Fuselage','engineIO':0,'sections':sections}};lines=[]
  for front in range(3):
   for back in range(3):
    for i in range(3):
     x=i+(10 if bad or front or back else 0);coords=[(x,1,0),(x,0,1),(x,-1,0),(x,0,-1)];lines.append('A '+str(front)+' '+str(back)+' '+str(i)+' '+' '.join(str(v)for q in coords for v in q)+' '+('6 3'if i==1 else'0 0'))
  (p/'LayoutProbes.txt').write_text('\n'.join(lines));rows=[[(i,1,0),(i,0,1),(i,-1,0),(i,0,-1),(i,1,0)]for i in range(3)];(p/'NativeGrid.txt').write_text('A 0 3 5\n'+'\n'.join(str(i/2)+' '+' '.join(str(v)for v in q)for i,row in enumerate(rows)for q in row));faces=[]
  for i in range(2):
   for j in range(4):faces.extend([[i*5+j,(i+1)*5+j,(i+1)*5+j+1],[i*5+j,(i+1)*5+j+1,i*5+j+1]])
  mesh={'nodes':sum(rows,[]),'faces':faces,'faceParts':[1]*len(faces),'parts':{1:{'geomId':'A'}}};return meta,mesh
 def test_native_planes_validate_roles_for_whole_curved_shell(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t);meta,mesh=self.build(p);r=read_semantics(p,meta,mesh,1);self.assertTrue(r['complete']);self.assertEqual(set(r['faces'].values()),{'external'})
 def test_bad_native_parameter_layout_stays_unknown(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t);meta,mesh=self.build(p,True);r=read_semantics(p,meta,mesh,1);self.assertFalse(r['layouts']['A']['verified']);self.assertEqual(r['unknownFaces'],len(mesh['faces']))
 def test_intentional_edge_is_not_a_smoothing_target(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t);meta,mesh=self.build(p);r=read_semantics(p,meta,mesh,1);self.assertEqual(smoothness(r,meta)['warnings'],1);s=smoothness(r,meta,[{'geomId':'A','stationId':'s1'}]);self.assertEqual(s['warnings'],0);self.assertTrue(s['stations'][0]['intentionalEdge'])
 def test_free_reverse_run_is_internal_not_a_fold_error(self):
  runs,outer=branches([{'localX':x}for x in [3,2,1,4,8]]);self.assertEqual(outer,(2,4));self.assertEqual(runs,[(0,2),(2,4)])
 def test_point_end_collapsed_by_native_does_not_reject_two_valid_ribs(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t);meta,mesh=self.build(p);meta['A']['sections'][0]['curveType']=0;lines=(p/'LayoutProbes.txt').read_text().splitlines();a=lines[0].split();a[4:16]=['1','1','0','1','0','1','1','-1','0','1','0','-1'];lines[0]=' '.join(a);(p/'LayoutProbes.txt').write_text('\n'.join(lines));r=read_semantics(p,meta,mesh,1);self.assertTrue(r['layouts']['A']['verified']);self.assertEqual(r['layouts']['A']['validatedPlaneCount'],2)
 def test_one_nonpoint_plane_is_insufficient_to_confirm_layout(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t);meta,mesh=self.build(p);meta['A']['sections'][0]['curveType']=0;meta['A']['sections'][2]['curveType']=0;r=read_semantics(p,meta,mesh,1);self.assertFalse(r['layouts']['A']['verified'])

class RepairTests(unittest.TestCase):
 def test_only_selected_outer_station_changes(self):
  xml=fixture_xml();r=change_surface(xml,pair_fixture(),'A',.01,1,[-1,20],set(),'ft',geoms);self.assertIsNotNone(r);after,ids=r;self.assertEqual(ids,['A1']);self.assertGreater(control_bound(xml,after,'ft'),0);self.assertLessEqual(control_bound(xml,after,'ft'),.02)
  a,b=geoms(xml)['B'][1],geoms(after)['B'][1];self.assertEqual(xml[a[0]:a[1]],after[b[0]:b[1]])
 def test_mirrored_closest_point_maps_to_base_body(self):
  xml=fixture_xml(2);pair=pair_fixture()|{'pointA':(5,-4,0),'pointB':(5,-4.001,0)};r=change_surface(xml,pair,'A',.01,1,[-1,20],set(),'ft',geoms);self.assertGreater(control_bound(xml,r[0],'ft'),0)
 def test_protected_station_cannot_be_modified(self):self.assertIsNone(change_surface(fixture_xml(),pair_fixture(),'A',.01,1,[-1,20],{'A1'},'ft',geoms))
 def test_between_rib_engine_u_prevents_automatic_body_edit(self):
  root=ET.fromstring(fixture_xml());pc=root.find('./Vehicle/Geom/ParmContainer');em=ET.SubElement(pc,'EngineModel')
  for k,v in [('GeomIOType',1),('InletFaceMode',1),('InletFaceU',.3),('InletFaceIndex',0),('InletLipMode',0),('InletLipIndex',0)]:ET.SubElement(em,k,Value=str(v))
  self.assertIsNone(change_surface(ET.tostring(root,encoding='unicode'),pair_fixture(),'A',.01,1,[-1,20],set(),'ft',geoms))
 def test_discrete_engine_u_protects_actual_rib_despite_stale_index(self):
  root=ET.fromstring(fixture_xml());pc=root.find('./Vehicle/Geom/ParmContainer');em=ET.SubElement(pc,'EngineModel')
  for k,v in [('GeomIOType',1),('InletFaceMode',1),('InletFaceU',.5),('InletFaceIndex',0),('InletLipMode',0),('InletLipIndex',0)]:ET.SubElement(em,k,Value=str(v))
  self.assertIsNone(change_surface(ET.tostring(root,encoding='unicode'),pair_fixture(),'A',.01,1,[-1,20],set(),'ft',geoms))
 def run_guard(self,preservation):
  p=pair_fixture();initial={'complete':True,'passed':False,'pairs':[p],'mesh':{'nodes':[(0,0,0),(10,0,0),(0,1,0)],'faces':[[0,1,2]],'faceParts':[1],'parts':[{'part':1,'geomId':'A'}]},'smoothness':{'stations':[],'complete':True}}
  final=copy.deepcopy(initial);final.update(passed=True);final['pairs']=[p|{'passed':True,'state':'clear','distanceFt':.02}]
  with patch('assembly_repair.assembly',side_effect=[{'report':initial},{'report':final},{'report':final}]),patch('assembly_repair.compare',return_value={'report':preservation}):return repair_assembly('unused',Path('.'),{'xml':fixture_xml(),'units':'ft','pairs':[{'a':'A','b':'B','minimumGapFt':.01,'toleranceFt':.0001}],'mutableIds':['A'],'budgetFt':.1,'zoneFt':[-1,20],'iterations':1},geoms)
 def test_native_lock_failure_never_returns_an_apply_xml(self):
  r=self.run_guard({'complete':True,'locksPassed':False,'components':[]});self.assertFalse(r['passed']);self.assertIsNone(r['xml'])
 def test_native_budget_failure_never_returns_an_apply_xml(self):
  r=self.run_guard({'complete':True,'locksPassed':True,'components':[{'id':'A','maximumMoveFt':.2}]});self.assertFalse(r['passed']);self.assertIsNone(r['xml'])
 def test_changed_reference_component_blocks_apply(self):
  r=self.run_guard({'complete':True,'locksPassed':True,'components':[{'id':'B','maximumMoveFt':.001,'parametersUnchanged':False}]});self.assertFalse(r['passed']);self.assertIsNone(r['xml'])

class QueueTests(unittest.TestCase):
 def wait(self,jobs,ident):
  until=time.monotonic()+3
  while time.monotonic()<until:
   r=jobs.poll(ident)
   if r['state']not in('queued','running'):return r
   time.sleep(.01)
  self.fail('Local test job did not finish')
 def test_cancelled_queued_job_does_not_unlock_another_operation(self):
  busy=threading.Lock();busy.acquire();jobs=Jobs(busy,lambda *a:{'ok':True});ident=jobs.start('assembly',{})['jobId'];jobs.cancel(ident);r=self.wait(jobs,ident);self.assertEqual(r['state'],'cancelled');self.assertTrue(busy.locked());busy.release()
 def test_completed_result_can_be_discarded_at_cancel_race(self):
  jobs=Jobs(threading.Lock(),lambda *a:{'ok':True});ident=jobs.start('assembly',{})['jobId'];self.assertEqual(self.wait(jobs,ident)['state'],'done');jobs.cancel(ident);r=jobs.poll(ident);self.assertEqual(r['state'],'cancelled');self.assertNotIn('result',r)
 def test_native_child_is_terminated_when_cancelled(self):
  event=threading.Event();context.cancel=event;timer=threading.Timer(.15,event.set);timer.start();start=time.monotonic()
  try:
   with self.assertRaises(InterruptedError):run_cancelable([sys.executable,'-c','import time;time.sleep(20)'],timeout=25)
   self.assertLess(time.monotonic()-start,3)
  finally:timer.cancel();context.cancel=None
 def test_discovery_supports_spaces_and_unicode(self):
  with tempfile.TemporaryDirectory(prefix='Studio путь ')as t:
   p=Path(t);a=p/'OpenVSP 3.51.0 & tools';b=p/'OpenVSP 3.55.0';a.mkdir();b.mkdir();(a/'vspscript.exe').touch();(b/'vspscript.exe').touch();r=discover_executables([p]);self.assertEqual(r[0],str((a/'vspscript.exe').resolve()))

if __name__=='__main__':unittest.main()
