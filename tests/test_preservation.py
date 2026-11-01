import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from assembly_audit import compare_samples,safe_pairs

def rows(xs,dy=0):
    return [[(x,dy,0),(x,1+dy,0)]for x in xs]

class PreservationTests(unittest.TestCase):
 def test_identity_retains_all_points_and_protected_lock(self):
    a=[rows([0,1,2,3])];r=compare_samples(a,a,[{'x0':0,'x1':3,'toleranceFt':1e-7}])
    self.assertTrue(r['complete']);self.assertEqual(r['maximumMoveFt'],0)
    self.assertEqual(r['sampleCount'],8);self.assertTrue(r['locks'][0]['passed'])
 def test_displacement_above_protected_budget_is_rejected(self):
    r=compare_samples([rows([0,1,2,3])],[rows([0,1,2,3],.02)],[{'x0':.5,'x1':2.5,'toleranceFt':.01}])
    self.assertFalse(r['locks'][0]['passed']);self.assertAlmostEqual(r['maximumMoveFt'],.02)
 def test_missing_end_cannot_disappear_from_protected_measurement(self):
    r=compare_samples([rows([0,1,2,3,4])],[rows([1,2,3,4])],[{'x0':0,'x1':4,'toleranceFt':.01}],False)
    self.assertFalse(r['complete']);self.assertFalse(r['locks'][0]['passed']);self.assertEqual(r['locks'][0]['skippedSampleCount'],2)
 def test_branch_topology_change_has_incomplete_correspondence(self):
    r=compare_samples([rows([2,1,0,1,2,3])],[rows([0,1,2,3,4,5])],[],False)
    self.assertFalse(r['complete'])
 def test_pair_criteria_reject_invalid_numbers_and_unknown_ids(self):
    for pairs in [[{'a':'A','b':'A'}],[{'a':'A','b':'C'}],[{'a':'A','b':'B','minimumGapFt':float('nan')}]]:
        with self.assertRaises(ValueError):safe_pairs(pairs,{'A','B'})

if __name__=='__main__':unittest.main()
