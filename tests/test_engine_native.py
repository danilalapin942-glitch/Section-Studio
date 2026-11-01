"""Opt-in integration checks against an actual OpenVSP 3.51 installation."""
import os
from pathlib import Path
import unittest
from engine_control import engine_update
ROOT=Path(__file__).resolve().parents[1]
EXE=os.environ.get('OPENVSP_TEST_EXE')
@unittest.skipUnless(EXE,'set OPENVSP_TEST_EXE to run native engine integration')
class NativeEngineTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.xml=(ROOT/'Prepared_models/MQ20_repaired_v01.vsp3').read_text(encoding='utf-8')
 def test_native_u_binding_and_index_coupling(self):
  r=engine_update(EXE,self.xml,'XCDIQYNZAG',[{'name':'InletLipMode','value':1},{'name':'InletLipU','value':.23}]);self.assertAlmostEqual(r['values']['InletLipU'],.23);self.assertIn('InletLipU',r['active'])
  r=engine_update(EXE,self.xml,'XCDIQYNZAG',[{'name':'InletLipMode','value':0},{'name':'InletLipIndex','value':1}]);self.assertEqual(r['values']['InletLipIndex'],1);self.assertAlmostEqual(r['values']['InletLipU'],1/(r['sectionCount']-1))
 def test_native_extension_and_index_limits(self):
  r=engine_update(EXE,self.xml,'XCDIQYNZAG',[{'name':'InletModeType','value':7},{'name':'ExtensionDistance','value':12},{'name':'AutoExtensionFlag','value':1}]);self.assertEqual(r['values']['InletModeType'],7);self.assertIn('AutoExtensionSet',r['active']);self.assertNotIn('ExtensionDistance',r['active'])
  r=engine_update(EXE,self.xml,'OOGDGRQXEU',[{'name':'InletLipIndex','value':999}]);self.assertEqual(r['values']['InletLipIndex'],r['sectionCount']-1)
if __name__=='__main__':unittest.main()
