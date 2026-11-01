"""Reliability contracts: interrupted writes, recovery, process crashes and trims."""
import copy,json,math,os,subprocess,sys,tempfile,time,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_storage import atomic_bytes,read_settings,write_settings,RecoveryStore
from instance_guard import InstanceGuard
from native_projection import anchor_map
from native_audit import process_failure
from section_studio_server import Studio
from surface_tools import read_semantics,smoothness
import test_v12

ROOT=Path(__file__).resolve().parents[1]
def project(name='Model'):
    return {'format':'section-studio','schema':1,'units':'ft','name':name,'strength':.7,'sections':[{'x':0,'width':0,'height':0,'z':0},{'x':5,'width':2,'height':2,'z':0},{'x':10,'width':0,'height':0,'z':0}],'shapeLocks':[{'geomId':'TEST','x0':1,'x1':2,'toleranceFt':.0001}]}

class StorageTests(unittest.TestCase):
    def test_interrupted_replace_retains_original_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory()as t:
            p=Path(t)/'settings.json';p.write_bytes(b'original')
            with patch('local_storage.os.replace',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):atomic_bytes(p,b'new')
            self.assertEqual(p.read_bytes(),b'original');self.assertEqual(list(Path(t).glob('*.tmp')),[])
    def test_corrupt_settings_fall_back_to_previous_complete_write(self):
        with tempfile.TemporaryDirectory()as t:
            p=Path(t)/'settings.json';write_settings(p,{'executable':'A'});write_settings(p,{'executable':'B'});p.write_bytes(b'{broken')
            value,warnings=read_settings(p);self.assertEqual(value['executable'],'A');self.assertTrue(any('восстановлены'in w for w in warnings))
    def test_corrupt_primary_does_not_destroy_good_settings_backup_on_save(self):
        with tempfile.TemporaryDirectory()as t:
            p=Path(t)/'settings.json';write_settings(p,{'executable':'A'});write_settings(p,{'executable':'B'});p.write_bytes(b'{broken');write_settings(p,{'executable':'C'});p.write_bytes(b'broken again');self.assertEqual(read_settings(p)[0]['executable'],'A')
    def test_recovery_keeps_three_verified_generations_and_exact_project(self):
        with tempfile.TemporaryDirectory(prefix='Recovery русский & ')as t:
            store=RecoveryStore(Path(t));last=None
            for i in range(5):last=store.save(project('Model'+str(i)))
            rows=store.listing()['snapshots'];self.assertEqual(len(rows),3);self.assertEqual([r['name']for r in rows],['Model4','Model3','Model2']);self.assertEqual(store.load(last['snapshot']['id'])['project'],project('Model4'))
    def test_recovery_does_not_rewrite_unchanged_project(self):
        with tempfile.TemporaryDirectory()as t:
            store=RecoveryStore(t);a=store.save(project());b=store.save(project());self.assertFalse(b['saved']);self.assertEqual(a['snapshot']['id'],b['snapshot']['id'])
    def test_corrupt_newest_snapshot_is_skipped_without_losing_previous(self):
        with tempfile.TemporaryDirectory()as t:
            store=RecoveryStore(t);old=store.save(project('Good'));new=store.save(project('New'));p=Path(t)/new['snapshot']['id'];v=json.loads(p.read_text());v['project']['name']='Tampered';p.write_text(json.dumps(v));listing=store.listing();self.assertEqual(listing['snapshots'][0]['name'],'Good');self.assertEqual(len(listing['warnings']),1)
            with self.assertRaises(ValueError):store.load(new['snapshot']['id'])
            self.assertEqual(store.load(old['snapshot']['id'])['project']['name'],'Good')
    def test_failed_recovery_write_retains_last_complete_snapshot(self):
        with tempfile.TemporaryDirectory()as t:
            store=RecoveryStore(t);old=store.save(project('Good'))
            with patch('local_storage.atomic_bytes',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):store.save(project('New'))
            self.assertEqual(store.load(old['snapshot']['id'])['project']['name'],'Good')
    def test_nonfinite_project_is_never_saved(self):
        with tempfile.TemporaryDirectory()as t:
            p=project();p['sections'][1]['width']=math.nan
            with self.assertRaises(ValueError):RecoveryStore(t).save(p)
            self.assertEqual(list(Path(t).glob('*')),[])
    def test_recovery_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory()as t:
            with self.assertRaises(ValueError):RecoveryStore(t).load('../settings.json')
    def test_oversized_project_is_rejected_before_disk_write(self):
        with tempfile.TemporaryDirectory()as t,patch('local_storage.MAX_RECOVERY_BYTES',100):
            with self.assertRaises(ValueError):RecoveryStore(t).save(project())
            self.assertEqual(list(Path(t).glob('*')),[])

class LaunchTests(unittest.TestCase):
    def test_os_lock_is_released_after_forced_process_exit(self):
        with tempfile.TemporaryDirectory(prefix='Instance русский & ')as t:
            lock=Path(t)/'instance.lock';code='import sys,time;sys.path.insert(0,sys.argv[1]);from instance_guard import InstanceGuard\nwith InstanceGuard(sys.argv[2]) as g:\n print("LOCKED",flush=True);time.sleep(20)'
            child=subprocess.Popen([sys.executable,'-c',code,str(ROOT),str(lock)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(),'LOCKED')
                with InstanceGuard(lock)as second:self.assertFalse(second.acquired)
                child.kill();child.wait(timeout=3)
                with InstanceGuard(lock)as recovered:self.assertTrue(recovered.acquired)
            finally:
                if child.poll()is None:child.kill();child.wait(timeout=3)
                child.stdout.close();child.stderr.close()
    def test_import_failure_is_logged_with_nonzero_exit_in_unicode_folder(self):
        with tempfile.TemporaryDirectory(prefix='Запуск & paths ')as t:
            p=Path(t);(p/'studio_bootstrap.py').write_bytes((ROOT/'studio_bootstrap.py').read_bytes());config=p/'данные/settings.json';env=dict(os.environ);env.pop('PYTHONPATH',None)
            r=subprocess.run([sys.executable,str(p/'studio_bootstrap.py'),'--config',str(config),'--no-browser'],cwd=p,capture_output=True,text=True,env=env,timeout=10)
            self.assertEqual(r.returncode,1);log=(config.parent/'launch.log').read_text();self.assertIn('ModuleNotFoundError',log);self.assertIn('Startup failed',log)
    def test_windows_dll_exit_codes_are_explained_signed_or_unsigned(self):
        for code in [0xc0000135,-1073741515]:self.assertIn('Не найдена DLL',process_failure(code))
        self.assertIn('Несовместимый',process_failure(0xc000007b))

class TrimTests(unittest.TestCase):
    def test_changed_count_projection_uses_visible_source_ids_only(self):
        a=[{'id':str(i)}for i in range(6)];b=[a[0],{'id':'inserted'},*a[1:]];la={'verified':True,'frontCaps':1,'backCaps':1,'sourceRange':{'start':1,'end':4}};lb={'verified':True,'frontCaps':1,'backCaps':1,'sourceRange':{'start':2,'end':5}};m=anchor_map(a,b,la,lb);self.assertEqual(m,[(0,0),(.2,.2),(.4,.4),(.6,.6),(.8,.8),(1,1)])
    def test_unsupported_native_engine_layout_remains_unknown(self):
        with tempfile.TemporaryDirectory()as t:
            p=Path(t);meta,mesh=test_v12.SemanticTests().build(p);(p/'LayoutProbes.txt').write_text('');(p/'NativeRanges.txt').write_text('A 0 2 0\n');sem=read_semantics(p,meta,mesh,1);self.assertFalse(sem['complete']);self.assertEqual(sem['unknownFaces'],len(mesh['faces']));self.assertFalse(smoothness(sem,meta)['complete'])

class RecoveryHTTPTests(unittest.TestCase):
    def test_auth_roundtrip_and_recovery_after_server_restart(self):
        import threading
        with tempfile.TemporaryDirectory()as t:
            config=Path(t)/'settings.json'
            def run(server):
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();return thread
            def request(server,path,data=None,token=True):
                headers={'Content-Type':'application/json'}
                if token:headers['X-Section-Studio']=server.token
                r=urllib.request.Request(server.origin+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
                with urllib.request.urlopen(r,timeout=5)as response:return json.load(response)
            server=Studio(config);thread=run(server)
            try:
                with self.assertRaises(urllib.error.HTTPError)as exc:request(server,'/api/recovery-list',token=False)
                self.assertEqual(exc.exception.code,403);saved=request(server,'/api/recovery-save',{'project':project()});self.assertEqual(request(server,'/api/recovery-load',{'id':saved['snapshot']['id']})['project'],project())
            finally:server.shutdown();server.server_close();thread.join(timeout=3)
            restarted=Studio(config);thread=run(restarted)
            try:self.assertEqual(request(restarted,'/api/recovery-load',{'id':saved['snapshot']['id']})['project'],project())
            finally:restarted.shutdown();restarted.server_close();thread.join(timeout=3)

if __name__=='__main__':unittest.main()
