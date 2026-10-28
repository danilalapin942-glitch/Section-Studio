"""Portable bridge checks; no OpenVSP installation needed for this suite."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from section_studio_server import Studio, geoms, merge_selected

XML = '<Vsp_Geometry><Vehicle><Geom><ParmContainer><ID>BODY1</ID></ParmContainer><GeomBase><TypeName>Fuselage</TypeName></GeomBase></Geom><Geom><ParmContainer><ID>BODY2</ID></ParmContainer><GeomBase><TypeName>Fuselage</TypeName></GeomBase></Geom><Geom><ParmContainer><ID>WING1</ID></ParmContainer><GeomBase><TypeName>Wing</TypeName></GeomBase></Geom></Vehicle></Vsp_Geometry>'


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.server = Studio(Path(self.folder.name)/'settings.json')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.folder.cleanup()

    def request(self, path, data=None, token=True, origin=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-Section-Studio'] = self.server.token
        if origin:
            headers['Origin'] = origin
        request = urllib.request.Request(self.server.origin+path, data=None if data is None else json.dumps(data).encode(), headers=headers)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def test_auth_and_foreign_origin(self):
        self.assertEqual(self.request('/api/status', token=False)[0], 403)
        self.assertEqual(self.request('/api/status', origin='https://example.com')[0], 403)
        self.assertEqual(self.request('/api/status')[0], 200)

    def test_no_source_or_settings_file_served(self):
        for path in ('/section_studio_server.py', '/native/sections.vspscript', '/settings.json', '/../README.txt'):
            self.assertEqual(self.request(path)[0], 404)

    def test_invalid_path_keeps_settings(self):
        previous = self.server.executable
        status, _ = self.request('/api/configure', {'executable': '/missing/vspscript.exe'})
        self.assertEqual(status, 400)
        self.assertEqual(self.server.executable, previous)
        self.assertFalse(self.server.config_path.exists())

    def test_no_client_scripts_allowed(self):
        status, _ = self.request('/api/prepare', {'xml': XML, 'kind': 'execute', 'script': 'untrusted'})
        self.assertEqual(status, 400)

    def test_invalid_units_and_selection(self):
        for data in ({'kind': 'wings', 'units': 'yards'}, {'kind': 'sections', 'selection': ['BODY1', 'BODY1']}, {'kind': 'sections', 'selection': ['BODY1', 'WING1']}):
            self.assertEqual(self.request('/api/prepare', {'xml': XML, **data})[0], 400)

    def test_busy_native_job(self):
        self.server.busy.acquire()
        try:
            status, result = self.request('/api/prepare', {'xml': XML, 'kind': 'sections', 'selection': ['BODY1', 'BODY2']})
            self.assertEqual(status, 400)
            self.assertIn('занят', result['error'])
        finally:
            self.server.busy.release()

    def test_no_executor_releases_lock(self):
        self.server.executable = None
        status, result = self.request('/api/prepare', {'xml': XML, 'kind': 'sections', 'selection': ['BODY1', 'BODY2']})
        self.assertEqual(status, 400)
        self.assertIn('vspscript', result['error'])
        self.assertFalse(self.server.busy.locked())

    def test_audit_input_and_busy_job_are_checked(self):
        for data in ({'units': 'yards', 'preset': 'source'}, {'units': 'ft', 'preset': 'arbitrary'}):
            self.assertEqual(self.request('/api/audit', {'xml': XML, **data})[0], 400)
        self.server.busy.acquire()
        try:
            self.assertEqual(self.request('/api/audit', {'xml': XML, 'units': 'ft', 'preset': 'source'})[0], 400)
        finally:
            self.server.busy.release()
        self.assertEqual(self.request('/api/verify-repair', {'xml': XML, 'candidateXml': '<bad>', 'units': 'ft', 'preset': 'source'})[0], 400)

    def test_merge_preserves_wing_and_top_level_xml(self):
        native = XML.replace('<ID>BODY1</ID>', '<ID>BODY1</ID><New>native curve</New>').replace('<TypeName>Wing</TypeName>', '<TypeName>Wing</TypeName><Different>serialization</Different>')
        expected = XML.replace('<ID>BODY1</ID>', '<ID>BODY1</ID><New>native curve</New>')
        self.assertEqual(merge_selected(XML, native, ['BODY1']), expected)
        self.assertEqual(geoms(XML).keys(), geoms(expected).keys())

    def test_dtd_and_duplicate_ids_rejected(self):
        for invalid in ('<!DOCTYPE Vsp_Geometry>'+XML, XML.replace('BODY2', 'BODY1')):
            with self.assertRaises(ValueError):
                geoms(invalid)

    def test_external_tri_without_openvsp_and_without_auth(self):
        self.server.executable=None
        data={'tri':'3 1\n0 0 0\n1 0 0\n0 1 0\n1 2 3\n1\n','units':'m','machline':{'mach':.5},'fileName':'CFD.tri'}
        self.assertEqual(self.request('/api/machline-tri',data,token=False)[0],403)
        status,r=self.request('/api/machline-tri',data);self.assertEqual(status,200)
        self.assertTrue(r['report']['externalMesh']);self.assertFalse(r['report']['cpCalculated'])
        self.assertAlmostEqual(r['report']['mesh']['nodes'][1][0],1/.3048)
        self.assertFalse(self.server.busy.locked())

    def test_external_tri_failure_releases_job_lock(self):
        for data in ({'tri':'broken','units':'ft'},{'tri':'3 1','units':'yard'},{'tri':'3 1','units':'ft','machline':{'mach':-1}}):
            self.assertEqual(self.request('/api/machline-tri',data)[0],400)
            self.assertFalse(self.server.busy.locked())


if __name__ == '__main__':
    unittest.main()
