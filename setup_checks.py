"""Portable discovery and an explicit native/HTTP installation self-test."""
import json,os,platform,re,shutil,sys,tempfile,threading,urllib.request,urllib.error
from pathlib import Path
from native_audit import run_script
from version import VERSION
from local_storage import RecoveryStore
from instance_guard import InstanceGuard

def discover_executables(roots=None):
 candidates=[];which=shutil.which('vspscript.exe'if os.name=='nt'else'vspscript')
 if which:candidates.append(Path(which))
 if os.environ.get('OPENVSP_ROOT'):candidates.append(Path(os.environ['OPENVSP_ROOT'])/('vspscript.exe'if os.name=='nt'else'vspscript'))
 app=Path(__file__).resolve().parent
 for base in [app,*list(app.parents)[:3]]:
  for folder in [base/'engines/OpenVSP',base/'OpenVSP']:
   for name in ['vspscript.exe','vspscript']:
    p=folder/name
    if p.is_file():candidates.append(p)
   if folder.is_dir():
    for sub in sorted(folder.glob('*'))[:100]:
     if sub.is_dir():
      for name in ['vspscript.exe','vspscript']:
       if(sub/name).is_file():candidates.append(sub/name)
 if roots is None:
  roots=[]
  if os.name=='nt':
   roots=[Path(v)for k in ['ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA']if(v:=os.environ.get(k))]+[Path('C:/'),Path('D:/')]
 for base in roots:
  try:
   for folder in sorted(Path(base).glob('OpenVSP*'))[:100]:
    if not folder.is_dir():continue
    for name in ['vspscript.exe','vspscript']:
     p=folder/name
     if p.is_file():candidates.append(p)
  except OSError:continue
 unique={str(p.resolve()):p for p in candidates if p.is_file()}
 return sorted(unique,key=lambda s:('3.51'not in s.lower(),s.lower()))

def self_test(root,server):
 report={'program':'Section Studio','version':VERSION,'platform':platform.platform(),'python':platform.python_version(),'pythonSupported':sys.version_info>=(3,10),'requiredFiles':{},'http':False,'native':{'available':bool(server.executable)},'passed':False}
 for name in ['Section_Studio.html','section_studio_server.py','studio_bootstrap.py','local_storage.py','instance_guard.py','version.py','assembly_audit.py','assembly_repair.py','surface_tools.py','native_projection.py','native/mesh.vspscript','calculation.py','Run_Calculations.py','engine_control.py','source/contour.js','source/sectioneditor.js','source/engineui.js']:
  report['requiredFiles'][name]=(root/name).is_file()
 thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 try:
  request=urllib.request.Request(server.origin+'/api/status',headers={'X-Section-Studio':server.token})
  with urllib.request.urlopen(request,timeout=5)as response:r=json.load(response)
  report['http']=r.get('version')==VERSION
  try:
   server.config_path.parent.mkdir(parents=True,exist_ok=True)
   with tempfile.TemporaryDirectory(prefix='StudioStorageCheck_',dir=server.config_path.parent)as t:
    store=RecoveryStore(Path(t)/'Recovery');project={'format':'section-studio','schema':1,'units':'ft','name':'SetupCheck','sections':[{'x':x}for x in range(3)]}
    saved=store.save(project);loaded=store.load(saved['snapshot']['id']);report['recoveryRoundtrip']=loaded['project']==project
    with InstanceGuard(Path(t)/'instance.lock')as first:
     server.instance_id=first.ident;first.publish({'instanceId':first.ident,'origin':server.origin})
     with InstanceGuard(Path(t)/'instance.lock')as second:
      report['instanceLock']=first.acquired and not second.acquired;report['instanceReuse']=second.existing_origin()==server.origin
  except (OSError,ValueError,RuntimeError)as exc:report['recoveryRoundtrip']=False;report['storageError']=str(exc)
  if server.executable:
   try:
    with tempfile.TemporaryDirectory(prefix='StudioSelfTest_')as t:
     p=Path(t);f=run_script(server.executable,p,'''int main(){ClearVSPModel();string g=AddGeom("POD");Update();WriteVSPFile("SelfTest.vsp3",SET_ALL);file info;info.open("SelfTest.txt","w");info.writeString(GetVSPVersion());info.close();if(GetNumTotalErrors()>0){Print("SECTION_STUDIO_ERROR");return 1;}Print("SECTION_STUDIO_SAVED: SelfTest.txt");return 0;}''','SelfTest.txt')
     version=f.read_text(encoding='utf-8').strip();report['native'].update(version=version,scriptReadWrite=(p/'SelfTest.vsp3').is_file(),supported=bool(re.search(r'3\.51\.',version)))
   except Exception as e:report['native']['error']=str(e)
  report['passed']=report['pythonSupported']and all(report['requiredFiles'].values())and report['http']and report.get('recoveryRoundtrip',False)and report.get('instanceLock',False)and report.get('instanceReuse',False)and report['native'].get('supported',False)and report['native'].get('scriptReadWrite',False)
 finally:server.shutdown();thread.join(timeout=3)
 return report
