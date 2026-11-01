"""Thread-local cancellation for native subprocesses and bounded searches."""
import subprocess,threading,time
context=threading.local()

def check_cancel():
 event=getattr(context,'cancel',None)
 if event is not None and event.is_set():raise InterruptedError('Проверка отменена. Геометрия не применена.')

def run_cancelable(args,**kwargs):
 event=getattr(context,'cancel',None)
 if event is None:return subprocess.run(args,**kwargs)
 timeout=kwargs.pop('timeout',180);check_cancel();p=subprocess.Popen(args,**kwargs);deadline=time.monotonic()+timeout
 try:
  while p.poll()is None:
   check_cancel()
   if time.monotonic()>deadline:raise subprocess.TimeoutExpired(args,timeout)
   event.wait(.1)
  check_cancel();return subprocess.CompletedProcess(args,p.returncode)
 except BaseException:
  if p.poll()is None:
   p.terminate()
   try:p.wait(timeout=2)
   except subprocess.TimeoutExpired:p.kill();p.wait(timeout=2)
  raise
