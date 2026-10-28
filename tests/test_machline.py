"""Analytical normals, controlled mesh faults and offset crossing cases."""
from pathlib import Path
import sys,math,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from machline_audit import inspect_machline,read_tri,write_tri,settings,compare_machline_reports,input_template,input_json

def mesh(nodes,faces,tags=None):
    tags=tags or [1]*len(faces)
    return dict(nodes=nodes,faces=faces,faceParts=tags,parts={p:dict(part=p,geom=p,surface=0,name='Body'+str(p),geomId='BODY'+str(p),thick=True,plate=0,copy=1,geomCopy=p) for p in set(tags)},wakeNodes=set(),refinementLevels=1)

def plane(degrees):
    return mesh([(0.,0.,0.),(1.,0.,math.tan(math.radians(degrees))),(0.,1.,0.)],[[0,1,2]])

def audit(m,**kwargs):
    return inspect_machline(m,{'formulation':'neumann-mass-flux',**kwargs})

class MachLineTests(unittest.TestCase):
    def codes(self,r):return {i['code'] for i in r['issues']}

    def test_subsonic_does_not_apply_supersonic_angle_limit(self):
        r=audit(plane(75),mach=.5)
        self.assertNotIn('machline_superinclined',self.codes(r));self.assertFalse(r['cpCalculated'])

    def test_M2_angle_boundary_matches_analytic_normal(self):
        self.assertNotIn('machline_superinclined',self.codes(audit(plane(25),mach=2)))
        self.assertIn('machline_characteristic',self.codes(audit(plane(30),mach=2)))
        self.assertIn('machline_superinclined',self.codes(audit(plane(35),mach=2)))

    def test_angle_warning_is_separate_from_stop(self):
        r=audit(plane(29.7),mach=2)
        self.assertIn('machline_near_characteristic',self.codes(r));self.assertEqual(r['summary']['superinclinedPanels'],0)

    def test_flow_direction_changes_inclination(self):
        a=audit(plane(35),mach=2);b=audit(plane(35),mach=2,alpha=20)
        self.assertIn('machline_superinclined',self.codes(a));self.assertNotIn('machline_superinclined',self.codes(b))
        self.assertAlmostEqual(b['panelInclinations'][0],15,places=9)

    def test_sonic_stop_and_near_sonic_warning(self):
        self.assertIn('machline_sonic',self.codes(audit(plane(0),mach=1)))
        self.assertIn('machline_transonic',self.codes(audit(plane(0),mach=.98)))

    def test_absolute_zero_area_criterion(self):
        r=audit(mesh([(0.,0.,0.),(1.,0.,0.),(0.,1e-13,0.)],[[0,1,2]]),mach=.5)
        self.assertIn('machline_zero_area',self.codes(r))

    def test_reader_collapse_can_create_zero_area(self):
        m=mesh([(0.,0.,0.),(1e-13,0.,0.),(0.,100.,0.)],[[0,1,2]])
        r=audit(m,mach=.5);self.assertEqual(r['summary']['mergedNodes'],1);self.assertIn('machline_zero_area',self.codes(r))

    def test_global_topology_between_parts_is_checked(self):
        m=mesh([(0,0,0),(1,0,0),(0,1,0),(0,-1,0),(0,0,1)],[[0,1,2],[1,0,3],[0,1,4]],[1,2,3])
        self.assertIn('machline_nonmanifold',self.codes(audit(m,mach=.5)))

    def test_flipped_normals_between_parts(self):
        m=mesh([(0,0,0),(1,0,0),(0,1,0),(0,-1,0)],[[0,1,2],[0,1,3]],[1,2])
        self.assertIn('machline_winding',self.codes(audit(m,mach=.5)))

    def test_nominal_offset_crosses_remote_panel(self):
        m=mesh([(0,0,0),(1,0,0),(0,1,0),(-1,-1,-.1),(2,-1,-.1),(-1,2,-.1)],[[0,1,2],[3,4,5]],[1,2])
        r=inspect_machline(m,{'mach':.5,'offset':.2})
        self.assertIn('machline_offset_crossing',self.codes(r));self.assertFalse(r['summary']['offsetLimited'])

    def test_mass_flux_ignores_offset(self):
        r=audit(plane(0),mach=.5,offset=5)
        self.assertNotIn('machline_offset_scale',self.codes(r));self.assertEqual(r['summary']['maxOffsetFt'],0.)

    def test_local_ratio_and_neumann_velocity_direct_offset(self):
        r=inspect_machline(plane(0),{'mach':.5,'offset':.02,'offsetType':'local'})
        self.assertAlmostEqual(r['summary']['maxOffsetFt'],.02*(1+math.sqrt(2))/2)
        r=inspect_machline(plane(0),{'mach':.5,'offset':.02,'offsetType':'local','formulation':'neumann-velocity'})
        self.assertEqual(r['summary']['maxOffsetFt'],.02);self.assertIn('machline_offset_type_ignored',self.codes(r))

    def test_reader_roundtrip_units_and_rejects_bad_input(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'Mesh.tri';p.write_text(write_tri(plane(0)))
            r=read_tri(p,1/.3048);self.assertAlmostEqual(r['nodes'][1][0],1/.3048)
            for text in ('3 1\n0 0 0\n1 0 0\n0 1 0\n1 2 9\n','3 1\nnan 0 0\n1 0 0\n0 1 0\n1 2 3\n'):
                p.write_text(text)
                with self.assertRaises(ValueError):read_tri(p)

    def test_downgrade_from_fatal_to_warning_is_accepted(self):
        base=dict(geomId='BODY1',part=1,count=2,metric=31)
        before={'issues':[dict(base,code='machline_superinclined',severity='error')]}
        after={'issues':[dict(base,code='machline_near_characteristic',severity='warning',metric=29.8)]}
        self.assertFalse(compare_machline_reports(before,after));self.assertTrue(compare_machline_reports(after,before))

    def test_invalid_settings_and_ft_template(self):
        for s in ({'mach':-1},{'mach':float('nan')},{'offset':0},{'alpha':90},{'offsetType':'unknown'},{'mach':True},[],False,0):
            with self.assertRaises(ValueError):settings(s)
        r=audit(plane(0),mach=.5);q=input_template(r)
        self.assertEqual(q['geometry']['file'],'Mesh.tri');self.assertEqual(q['geometry']['mirror_about'],'none')
        self.assertEqual(q['flow']['freestream_mach_number'],.5)

    def test_json_mantissa_matches_upstream_formatted_reader(self):
        import json
        data={'offset':1e-7,'small':1.25e-20,'large':1e30,'name':'file1e-7'}
        text=input_json(data);self.assertIn('1.0e-07',text);self.assertIn('1.25e-20',text)
        self.assertEqual(json.loads(text),data)

    def test_offset_below_coordinate_precision_is_flagged(self):
        r=inspect_machline(plane(0),{'mach':.5,'offset':1e-21})
        self.assertIn('machline_offset_roundoff',self.codes(r))

    def test_fourth_vertex_column_is_ignored_like_upstream(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'Mesh.tri';p.write_text('3 1\n0 0 0 12\n1 0 0 13\n0 1 0 14\n1 2 3\n')
            self.assertEqual(read_tri(p)['nodes'][1],(1.,0.,0.))

if __name__=='__main__':unittest.main()
