"""Atomic local settings and bounded, checksum-verified recovery snapshots."""
from __future__ import annotations
import hashlib,json,os,secrets,threading,time
from datetime import datetime,timezone
from pathlib import Path
from version import VERSION

MAX_RECOVERY_BYTES=60*1024*1024

def encode(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True,allow_nan=False).encode('utf-8')

def atomic_bytes(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+secrets.token_hex(8)+'.tmp')
    try:
        with temporary.open('xb')as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:
        try:temporary.unlink(missing_ok=True)
        except OSError:pass

def read_settings(path):
    path=Path(path);errors=[]
    for candidate in [path,path.with_suffix(path.suffix+'.bak')]:
        try:
            raw=candidate.read_bytes()
            if len(raw)>65536:raise ValueError('Настройки превышают предел 64 КБ.')
            value=json.loads(raw)
            if not isinstance(value,dict):raise ValueError('Настройки должны быть объектом JSON.')
            return value,errors+(['Настройки восстановлены из резервной копии.']if candidate!=path else[])
        except FileNotFoundError:continue
        except (OSError,ValueError,UnicodeError)as exc:errors.append('Не удалось прочитать '+candidate.name+': '+str(exc))
    return {},errors

def write_settings(path,value):
    path=Path(path);raw=encode(value)
    if path.exists():
        try:
            previous=path.read_bytes();old=json.loads(previous)
            if isinstance(old,dict)and len(previous)<=65536:atomic_bytes(path.with_suffix(path.suffix+'.bak'),previous)
        except (OSError,ValueError,UnicodeError):pass
    atomic_bytes(path,raw)

def validate_project(project):
    if not isinstance(project,dict)or project.get('format')!='section-studio'or project.get('schema')not in(1,2)or project.get('units')!='ft':raise ValueError('Нужен проект Section Studio в футах.')
    if not isinstance(project.get('name'),str)or not project['name'].strip()or len(project['name'])>100:raise ValueError('Неверное имя проекта восстановления.')
    bodies=project.get('bodies')if project['schema']==2 else[project]
    if not isinstance(bodies,list)or not 1<=len(bodies)<=2:raise ValueError('Неверные корпуса проекта восстановления.')
    for body in bodies:
        if not isinstance(body,dict)or not isinstance(body.get('sections'),list)or not 3<=len(body['sections'])<=128:raise ValueError('Неверные станции проекта восстановления.')
    raw=encode(project)
    if len(raw)>MAX_RECOVERY_BYTES:raise ValueError('Автосохранение: предел проекта 60 МБ. Сохрани JSON вручную.')
    return raw

class RecoveryStore:
    """Three generations. A failed write never replaces a verified snapshot."""
    def __init__(self,directory,validator=None):
        self.directory=Path(directory);self.lock=threading.RLock();self.validator=validator
    def _read(self,path):
        raw=path.read_bytes()
        if len(raw)>MAX_RECOVERY_BYTES+65536:raise ValueError('Снимок восстановления слишком большой.')
        record=json.loads(raw)
        if not isinstance(record,dict)or record.get('format')!='section-studio-recovery'or record.get('schema')!=1:raise ValueError('Неверный формат восстановления.')
        project=record.get('project');body=validate_project(project)
        if not secrets.compare_digest(hashlib.sha256(body).hexdigest(),str(record.get('sha256',''))):raise ValueError('Не совпадает контрольная сумма снимка.')
        if self.validator:self.validator(project)
        return record
    def _records(self):
        records=[];errors=[]
        if not self.directory.exists():return records,errors
        for path in sorted(self.directory.glob('snapshot-*.json'),reverse=True)[:12]:
            try:
                record=self._read(path);records.append((path,record))
            except (OSError,ValueError,UnicodeError,TypeError)as exc:errors.append({'file':path.name,'message':str(exc)})
        return records,errors
    @staticmethod
    def _entry(path,record):
        return {'id':path.name,'name':record['project']['name'],'savedAt':record['savedAt'],'sha256':record['sha256'],'version':record.get('version'),'sourceName':(record['project'].get('source')or{}).get('name')}
    def listing(self):
        with self.lock:
            records,errors=self._records()
            return {'ok':True,'snapshots':[self._entry(p,r)for p,r in records[:3]],'warnings':errors,'available':True}
    def save(self,project):
        raw=validate_project(project)
        if self.validator:self.validator(project)
        digest=hashlib.sha256(raw).hexdigest()
        with self.lock:
            records,_=self._records()
            if records and records[0][1]['sha256']==digest:return {'ok':True,'saved':False,'snapshot':self._entry(*records[0])}
            record={'format':'section-studio-recovery','schema':1,'version':VERSION,'savedAt':datetime.now(timezone.utc).isoformat(),'sha256':digest,'project':project}
            path=self.directory/('snapshot-'+str(time.time_ns()).zfill(20)+'-'+secrets.token_hex(4)+'.json')
            atomic_bytes(path,encode(record))
            # Keep three verified generations and at most three damaged files
            # for diagnosis. No source VSP3 or manually saved JSON is touched.
            for old,_ in records[2:]:
                try:old.unlink(missing_ok=True)
                except OSError:pass
            valid={p for p,_ in records}|{path};damaged=[p for p in self.directory.glob('snapshot-*.json')if p not in valid]
            for old in sorted(damaged,reverse=True)[3:]:
                try:old.unlink(missing_ok=True)
                except OSError:pass
            return {'ok':True,'saved':True,'snapshot':self._entry(path,record)}
    def load(self,ident):
        import re
        if not isinstance(ident,str)or not re.fullmatch(r'snapshot-[0-9]{20}-[a-f0-9]{8}\.json',ident):raise ValueError('Неверный снимок восстановления.')
        with self.lock:
            record=self._read(self.directory/ident)
            return {'ok':True,'snapshot':self._entry(self.directory/ident,record),'project':record['project']}
