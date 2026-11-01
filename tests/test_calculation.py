import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from calculation import normalize_plan, convergence, topology, parse_vspaero, parse_machline, execute, report_path, refined_xml, write_outputs, recover_interrupted, digest, bundle
from native_control import context

XML='''<Vsp_Geometry><Vehicle><Geom><ParmContainer><ID>WING1</ID><Name>Wing</Name><Shape><Tess_W Value="33"/></Shape></ParmContainer><GeomBase><TypeName>Wing</TypeName></GeomBase></Geom></Vehicle></Vsp_Geometry>'''


class PlanTests(unittest.TestCase):
    def test_standalone_bodies_require_explicit_reference_quantities(self):
        xml=XML.replace('<TypeName>Wing</TypeName>','<TypeName>Fuselage</TypeName>')
        with self.assertRaises(ValueError):normalize_plan({},xml)
        r=normalize_plan({'referenceMode':'manual','manualReferences':{'areaFt2':math.pi,'spanFt':2.,'lengthFt':2.}},xml)
        self.assertIsNone(r['referenceWing'])
        self.assertAlmostEqual(r['manualReferences']['areaFt2'],math.pi)

    def test_plan_rejects_transonic_and_nonfinite_inputs(self):
        for bad in [{'machs':[1.]},{'alphas':[2.,math.nan]},{'threads':True},{'alphas':[2.,2.]},{'referenceWing':'UNKNOWN'},{'solvers':['machline','machline']}]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):normalize_plan(bad,XML)

    def test_reference_wing_and_moment_origin_are_explicit(self):
        p=normalize_plan({'momentReferenceFt':[1.,2.,3.]},XML)
        self.assertEqual(p['referenceWing'],'WING1')
        self.assertEqual(p['momentReferenceFt'],[1.,2.,3.])
        self.assertEqual(p['meshMethod'],'cfd')

    def test_refinement_changes_only_sampling(self):
        import xml.etree.ElementTree as ET
        root=ET.fromstring(refined_xml(XML,'Fine'))
        self.assertEqual(root.findtext('.//ID'),'WING1')
        self.assertEqual(root.find('.//Tess_W').get('Value'),'33')


class ConvergenceTests(unittest.TestCase):
    def cases(self):
        rows=[]
        for alpha in [2.,4.]:
            for level,value in [('Coarse',.1),('Medium',.2),('Fine',.204)]:
                rows.append(dict(solver='machline',mach=.3,alpha=alpha,beta=0.,level=level,coefficients=dict(CL=value,CD=.001,CY=0.,Cl=0.,Cm=-.2,Cn=0.)))
        return rows

    def test_fine_admission_and_coarse_trend_are_separate(self):
        r=convergence(self.cases(),normalize_plan({'solvers':['machline'],'alphas':[2,4]},XML))
        self.assertTrue(r['passed'])
        self.assertFalse(r['cases'][0]['comparisons'][0]['passed'])
        self.assertTrue(r['cases'][0]['comparisons'][1]['passed'])

    def test_missing_grid_cannot_pass(self):
        r=convergence(self.cases()[:-1],normalize_plan({'solvers':['machline'],'alphas':[2,4]},XML))
        self.assertFalse(r['passed'])

    def test_near_zero_uses_absolute_tolerance(self):
        cases=self.cases()
        for c in cases:c['coefficients']['CD']=.0001 if c['level']=='Fine' else .0002
        self.assertTrue(convergence(cases,normalize_plan({'solvers':['machline'],'alphas':[2,4]},XML))['passed'])


class TopologyTests(unittest.TestCase):
    def mesh(self):
        return dict(nodes=[(0,0,0),(1,0,0),(0,1,0),(0,0,1)],faces=[[0,2,1],[0,1,3],[0,3,2],[1,2,3]],faceParts=[1]*4,parts={})

    def test_closed_outward_and_reversed_volume(self):
        m=self.mesh();r=topology(m)
        self.assertTrue(r['closed'] and r['outward'])
        m['faces']=[f[::-1] for f in m['faces']]
        self.assertFalse(topology(m)['outward'])

    def test_hole_and_nonmanifold_are_detected(self):
        m=self.mesh();m['faces'].pop();self.assertFalse(topology(m)['closed'])
        m=self.mesh();m['faces'].append(m['faces'][0]);m['faceParts'].append(1);self.assertGreater(topology(m)['nonmanifoldEdges'],0)


class ParserTests(unittest.TestCase):
    def test_vspaero_reads_real_space_separated_residual_columns(self):
        headers='Beta Mach AoA CLi CDi CSi CMix CMiy CMiz CDtot CDo CLwtot CDwtot'
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'Model.polar').write_text(headers+'\n0 .3 2 .2 .003 0 0 -.4 0 .01 .007 .2 .003\n')
            (p/'Model.history').write_text('Iter CLtot CDtot L2 Residual Max Residual\n1 .1 .02 1 2\n2 .2 .01 -2 -1\n3 .2 .01 -4 -3\n')
            r=parse_vspaero(p,{'returncode':0},.3,2.,0.)
            self.assertTrue(r['iterationConverged'])
            self.assertEqual(r['residual']['L2Residual'],-4)
            with self.assertRaises(ValueError):parse_vspaero(p,{'returncode':0},.4,2.,0.)

    def test_undefined_auxiliary_efficiency_does_not_invalidate_finite_body_loads(self):
        headers='Beta Mach AoA CLi CDi CSi CMix CMiy CMiz Ew CDtot'
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'Model.polar').write_text(headers+'\n0 .3 2 .2 .003 0 0 -.4 0 inf nan\n')
            (p/'Model.history').write_text('Iter CLtot CDtot L2 Residual Max Residual\n1 .1 .02 1 2\n2 .2 .01 -2 -1\n3 .2 .01 -4 -3\n')
            r=parse_vspaero(p,{'returncode':0},.3,2.,0.)
            self.assertTrue(r['iterationConverged']);self.assertIsNone(r['additional']['CDtotal'])
            json.dumps(r,allow_nan=False)
            (p/'Model.polar').write_text(headers+'\n0 nan 2 .2 .003 0 0 -.4 0 inf 0\n')
            with self.assertRaises(ValueError):parse_vspaero(p,{'returncode':0},.3,2.,0.)

    def test_machline_unsolved_status_has_no_false_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'Report.json').write_text(json.dumps({'solver_results':{'solver_status_code':1}}));(p/'solver.log').write_text('not converged')
            with self.assertRaisesRegex(ValueError,'solver_status_code=1'):
                parse_machline(p,{'returncode':0},.3,2.,0.,{})

    def test_moment_adapter_preserves_raw_values_and_finite_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            raw={'solver_results':{'solver_status_code':0,'residual':{'norm':1e-10}},'total_forces':{'Cx':.01,'Cy':0.,'Cz':.2},'total_moments':{'CMx':0.,'CMy':-20.,'CMz':0.},'input':{'geometry':{'reference':{'area':100.}}},'pressure_calculations':{'isentropic_rule':{'max':1.,'min':-2.}}}
            for f in ['Body.vtk','ControlPoints.vtk']:(p/f).write_text('fixture')
            (p/'Report.json').write_text(json.dumps(raw));s=normalize_plan({},XML)
            r=parse_machline(p,{'returncode':0},.3,0.,0.,s)
            self.assertEqual(r['coefficients']['Cm'],-.2)
            self.assertEqual(r['rawMoments']['CMy'],-20.)
            raw['pressure_calculations']['isentropic_rule']['min']=math.nan;(p/'Report.json').write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError,'NaN/Inf'):parse_machline(p,{'returncode':0},.3,0.,0.,s)
            raw['pressure_calculations']['isentropic_rule']['min']=-2.
            raw['total_forces']['Cz']=math.nan;(p/'Report.json').write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError,'NaN/Inf'):parse_machline(p,{'returncode':0},.3,0.,0.,s)



class AxisConventionTests(unittest.TestCase):
    def parse(self,alpha,beta):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);raw={'solver_results':{'solver_status_code':0,'residual':{'norm':1e-10}},'total_forces':{'Cx':.1,'Cy':.2,'Cz':.3},'total_moments':{'CMx':20.,'CMy':40.,'CMz':60.},'input':{'geometry':{'reference':{'area':100.,'length':2.}}},'pressure_calculations':{'isentropic_rule':{'max':1.,'min':-2.}}}
            for f in ['Body.vtk','ControlPoints.vtk']:(p/f).write_text('fixture')
            (p/'Report.json').write_text(json.dumps(raw))
            return parse_machline(p,{'returncode':0},.3,alpha,beta,normalize_plan({},XML),{'spanFt':10.})
    def test_roll_and_yaw_use_span_and_pitch_uses_chord(self):
        r=self.parse(0.,0.);self.assertAlmostEqual(r['coefficients']['Cl'],.04);self.assertAlmostEqual(r['coefficients']['Cm'],.4);self.assertAlmostEqual(r['coefficients']['Cn'],.12)
    def test_sideforce_is_transformed_to_wind_axes(self):
        r=self.parse(4.,10.);a,b=math.radians(4),math.radians(10);self.assertAlmostEqual(r['coefficients']['CY'],-math.cos(a)*math.sin(b)*.1+math.cos(b)*.2-math.sin(a)*math.sin(b)*.3)


class ArtifactTests(unittest.TestCase):
    def test_interrupted_series_is_retained_without_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/('a'*24);folder.mkdir();p=folder/'report.json';p.write_text(json.dumps({'id':'a'*24,'state':'running','passed':True,'cases':[]}))
            self.assertEqual(recover_interrupted(tmp),['a'*24]);r=json.loads(p.read_text());self.assertEqual(r['state'],'interrupted');self.assertFalse(r['passed']);self.assertEqual(recover_interrupted(tmp),[])
    def test_bundle_contains_exact_file_hashes_and_csv(self):
        import zipfile,hashlib
        with tempfile.TemporaryDirectory() as tmp:
            ident='b'*24;folder=Path(tmp)/ident;folder.mkdir();(folder/'Source.vsp3').write_text('source')
            r={'id':ident,'state':'rejected','passed':False,'cases':[]};(folder/'report.json').write_text(json.dumps(r));(folder/'ignored.adb').write_bytes(b'raw')
            path=bundle(tmp,ident)
            with zipfile.ZipFile(path) as z:
                self.assertNotIn('ignored.adb',z.namelist());self.assertIn('results.csv',z.namelist());m=json.loads(z.read('artifact_manifest.json'))
                for name,v in m['files'].items():self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(),v['sha256'])

class ProcessTests(unittest.TestCase):
    def test_timeout_returns_no_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TimeoutError):execute([sys.executable,'-c','import time; time.sleep(5)'],Path(tmp),'run.log',.15)

    def test_cancel_aborts_process(self):
        event=threading.Event();context.cancel=event
        timer=threading.Timer(.2,event.set);timer.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(InterruptedError):execute([sys.executable,'-c','import time; time.sleep(5)'],Path(tmp),'run.log',10)
        finally:
            context.cancel=None;timer.cancel()

    def test_report_ident_rejects_traversal(self):
        for bad in ['../x','f'*25,'../'+'a'*24,'A'*24]:
            with self.assertRaises(ValueError):report_path(Path('.'),bad)


if __name__=='__main__':unittest.main()
