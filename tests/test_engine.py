import copy
import unittest
from engine_control import active_parameters,engine_update,PARMS

BASE={k:0 for k in PARMS}
BASE.update(GeomIOType=2,GeomInType=1,GeomOutType=1,InletModeType=3,OutletModeType=3)
class EngineTests(unittest.TestCase):
 def test_whole_engine_has_lip_binding_and_hides_unused_faces(self):
  a=active_parameters(BASE)
  self.assertIn('InletLipIndex',a);self.assertIn('OutletLipIndex',a)
  self.assertNotIn('InletFaceIndex',a);self.assertNotIn('OutletFaceIndex',a)
 def test_u_binding_replaces_index_only_for_selected_station(self):
  v={**BASE,'InletLipMode':1};a=active_parameters(v)
  self.assertIn('InletLipU',a);self.assertNotIn('InletLipIndex',a);self.assertIn('OutletLipIndex',a)
 def test_native_flowthrough_locks_dependent_outlet(self):
  v={**BASE,'GeomInType':0,'InletModeType':0};a=active_parameters(v)
  self.assertNotIn('GeomOutType',a);self.assertNotIn('OutletModeType',a);self.assertIn('OutletFaceIndex',a)
 def test_extension_switches_manual_distance_and_automatic_set(self):
  v={**BASE,'InletModeType':7};a=active_parameters(v)
  self.assertIn('ExtensionDistance',a);self.assertNotIn('AutoExtensionSet',a)
  v['AutoExtensionFlag']=1;a=active_parameters(v)
  self.assertNotIn('ExtensionDistance',a);self.assertIn('AutoExtensionSet',a)
 def test_none_deactivates_geometry_controls(self):
  self.assertEqual(active_parameters({**BASE,'GeomIOType':0}),['EngineShowStationsFlag','GeomIOType'])
 def test_mutation_input_is_whitelisted_before_native_execution(self):
  xml='<Vsp_Geometry><Vehicle><Geom><ParmContainer><ID>BODY</ID></ParmContainer><GeomBase><TypeName>Fuselage</TypeName></GeomBase></Geom></Vehicle></Vsp_Geometry>'
  for patch in [[{'name':'not a parameter','value':1}],[{'name':'GeomIOType','value':float('nan')}],[{'name':'GeomIOType','value':'1'}],{}]:
   with self.subTest(patch=patch),self.assertRaises(ValueError):engine_update('/not-executed',xml,'BODY',patch)
  with self.assertRaises(ValueError):engine_update('/not-executed',xml,'MISSING',[])
if __name__=='__main__':unittest.main()
