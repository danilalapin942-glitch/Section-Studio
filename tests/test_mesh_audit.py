"""Controlled defects and thin/thick exceptions, independent of wind-tunnel data."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mesh_audit import inspect_mesh, read_vspgeom, compare_reports
from native_audit import check_repair_invariants
from section_studio_server import geoms


def mesh(nodes, faces, thick=True, wake=()):
    return {'nodes': nodes, 'faces': faces, 'faceParts': [1]*len(faces),
            'parts': {1: {'part': 1, 'geom': 0, 'surface': 0, 'name': 'Body', 'geomId': 'BODY1',
                          'thick': thick, 'plate': 0, 'copy': 1, 'geomCopy': 1}},
            'wakeNodes': set(wake), 'refinementLevels': 1}


class MeshTests(unittest.TestCase):
    def test_thin_open_boundary_is_expected(self):
        nodes = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        r = inspect_mesh(mesh(nodes, [[0, 1, 2], [0, 2, 3]], False))
        self.assertFalse(r['issues'])
        self.assertFalse(r['cpCalculated'])

    def test_closed_thick_tetrahedron_has_no_topology_errors(self):
        r = inspect_mesh(mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
                              [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]]))
        self.assertEqual(r['summary']['errors'], 0)
        self.assertNotIn('mesh_open_thick_boundary', [i['code'] for i in r['issues']])

    def test_flipped_neighbour_and_duplicate_coordinates_detected(self):
        nodes = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 0), (1, 0, 0), (1, 1, 0)]
        r = inspect_mesh(mesh(nodes, [[0, 1, 2], [0, 3, 2], [4, 5, 6]], False))
        codes = [i['code'] for i in r['issues']]
        self.assertIn('mesh_winding', codes)
        self.assertIn('mesh_duplicate', codes)

    def test_collinear_and_sliver_panels_detected(self):
        r = inspect_mesh(mesh([(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, .0001, 0)], [[0, 1, 2], [0, 1, 3]], False))
        codes = [i['code'] for i in r['issues']]
        self.assertIn('mesh_degenerate', codes)
        self.assertIn('mesh_sliver', codes)

    def test_engine_and_symmetry_boundaries_are_separate(self):
        m = mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [[0, 1, 2]])
        a = inspect_mesh(m)
        b = inspect_mesh(m, {'engine': {'BODY1': 3}})
        self.assertTrue(any(i['severity'] == 'warning' for i in a['issues']))
        self.assertTrue(all(i['severity'] == 'info' for i in b['issues']))
        self.assertTrue(compare_reports(b, a))
        self.assertFalse(compare_reports(a, b))

    def test_report_comparison_rejects_worsened_metric_with_same_count(self):
        report = {'issues': [{'severity': 'warning', 'code': 'mesh_sliver', 'geomId': 'BODY1', 'part': 1, 'count': 1, 'metric': 101.}]}
        after = {'issues': [{**report['issues'][0], 'metric': 140.}]}
        self.assertTrue(compare_reports(report, after))
        self.assertFalse(compare_reports(after, report))

    def test_dense_degenerate_cluster_remains_bounded(self):
        m = mesh([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [[0, 1, 2]]*1500, False)
        r = inspect_mesh(m)
        self.assertTrue(r['summary']['proximityLimited'])
        self.assertLessEqual(r['summary']['proximityCandidateVisits'], 2_000_001)

    def test_mixed_junction_does_not_create_nonmanifold_false_alarm(self):
        m = mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1)], [[0, 1, 2], [1, 0, 3], [0, 1, 4]])
        m['faceParts'] = [1, 1, 2]
        m['parts'][2] = {**m['parts'][1], 'part': 2, 'geomCopy': 2, 'thick': False}
        self.assertNotIn('mesh_nonmanifold', [i['code'] for i in inspect_mesh(m)['issues']])
        m['faceParts'] = [1, 1, 1]
        self.assertIn('mesh_nonmanifold', [i['code'] for i in inspect_mesh(m)['issues']])

    def test_close_unconnected_centres_are_detected(self):
        m = mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, .01), (1, 0, .01), (0, 1, .01)], [[0, 1, 2], [3, 4, 5]], False)
        m['faceParts'] = [1, 2]
        m['parts'][2] = {**m['parts'][1], 'part': 2, 'geomCopy': 2, 'geomId': 'BODY2'}
        self.assertIn('mesh_near_centers', [i['code'] for i in inspect_mesh(m)['issues']])

    def test_different_overlapping_polygons_with_one_centre_are_detected(self):
        m = mesh([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0), (-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)],
                 [[0, 1, 2, 3], [4, 5, 6, 7]], False)
        codes = [i['code'] for i in inspect_mesh(m)['issues']]
        self.assertIn('mesh_coincident_centers', codes)
        self.assertNotIn('mesh_duplicate', codes)

    def test_v3_parser_subsurface_tag_and_wrapped_wake(self):
        with tempfile.TemporaryDirectory() as name:
            f = Path(name)
            (f/'mesh.vkey').write_text('# VSPGEOM v3 Tag Key File\nmesh.vspgeom\n1\n\n# part#,geom#,surf#,gname,gid,thick,plate,copy#,geomcopy#\n1,0,0,Body,BODY1,0,3,1,1\n\n1\n\n# tag#,part#,ssname1,ssid1\n9,1\n')
            (f/'mesh.vspgeom').write_text('# vspgeom v3\n1\n3 1 1\n0 0 0\n1 0 0\n0 1 0\n1\n3 1 2 3\n9 0 0 0 1 0 0 1\n1 1\n1\n3 1 1 2\n3\n')
            m = read_vspgeom(f/'mesh.vspgeom', f/'mesh.vkey', 1/.3048)
            self.assertEqual(m['faceParts'], [1])
            self.assertEqual(m['wakeNodes'], {0, 1, 2})
            self.assertAlmostEqual(m['nodes'][1][0], 1/.3048)
            (f/'mesh.vspgeom').write_text('# vspgeom v3\n1\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n1\n3 1 2 4\n')
            with self.assertRaises(ValueError):
                read_vspgeom(f/'mesh.vspgeom', f/'mesh.vkey')

    def test_repair_rejects_external_changes_and_station_x_changes(self):
        xml = '<Vsp_Geometry><Vehicle><Geom><ParmContainer><ID>BODY1</ID></ParmContainer><GeomBase><TypeName>Fuselage</TypeName></GeomBase><FuselageGeom><XSecSurf><XSec><ParmContainer><XSec><XLocPercent Value="0"/></XSec></ParmContainer></XSec></XSecSurf></FuselageGeom></Geom><Geom><ParmContainer><ID>WING1</ID></ParmContainer><GeomBase><TypeName>Wing</TypeName></GeomBase></Geom></Vehicle></Vsp_Geometry>'
        check_repair_invariants(xml, xml, 'BODY1', geoms)
        for candidate in (xml.replace('TypeName>Wing', 'TypeName>Pod'), xml.replace('Value="0"', 'Value="0.1"')):
            with self.assertRaises(ValueError):
                check_repair_invariants(xml, candidate, 'BODY1', geoms)


if __name__ == '__main__':
    unittest.main()
