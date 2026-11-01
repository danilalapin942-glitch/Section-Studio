"""An OS-held instance lock. A crashed process releases it automatically."""
import errno,json,os,secrets,time,urllib.request
from pathlib import Path

class InstanceGuard:
    def __init__(self,path):self.path=Path(path);self.file=None;self.acquired=False;self.ident=secrets.token_hex(16)
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(self.path,os.O_RDWR|os.O_CREAT|getattr(os,'O_BINARY',0),0o600);self.file=os.fdopen(fd,'r+b',buffering=0)
        try:
            self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.acquired=True
        except OSError as exc:
            self.file.close();self.file=None
            if exc.errno not in(errno.EACCES,errno.EAGAIN,errno.EDEADLK):raise
        if self.acquired:
            try:self.publish({'instanceId':self.ident,'starting':True})
            except BaseException:self.file.close();self.file=None;self.acquired=False;raise
        return self
    def publish(self,value):
        if not self.acquired:raise RuntimeError('Instance lock is not held')
        raw=b'\n'+json.dumps(value,ensure_ascii=False).encode('utf-8');self.file.seek(0);self.file.write(raw);self.file.truncate();os.fsync(self.file.fileno())
    def existing_origin(self,timeout=3):
        import re
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                # Byte zero is locked on Windows. Read only the JSON after it.
                with self.path.open('rb')as f:f.seek(1);raw=f.read(65537)
                if len(raw)>65536:raise ValueError('Invalid instance metadata')
                data=json.loads(raw);origin=data.get('origin','');ident=data.get('instanceId')
                if not re.fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}',origin)or not 1<=int(origin.rsplit(':',1)[1])<=65535 or not isinstance(ident,str):raise ValueError('Instance is starting')
                with urllib.request.urlopen(origin+'/api/instance',timeout=.5)as response:state=json.load(response)
                if state.get('instanceId')==ident:return origin
            except (OSError,ValueError,TypeError):pass
            time.sleep(.1)
        raise RuntimeError('Section Studio уже запускается или не отвечает. Проверь окно работающей программы и launch.log.')
    def __exit__(self,*_):
        if self.file:
            try:
                if self.acquired:
                    self.publish({})
                    if os.name=='nt':
                        import msvcrt
                        self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
            finally:self.file.close();self.file=None

