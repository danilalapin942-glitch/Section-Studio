"""Bounded local job queue; cancellation never applies a stale result."""
import secrets,threading,time
from native_control import context,check_cancel

class Jobs:
 def __init__(self,busy,runner):self.busy=busy;self.runner=runner;self.lock=threading.RLock();self.jobs={}
 def start(self,kind,payload):
  with self.lock:
   active=[j for j in self.jobs.values()if j['state']in('queued','running')]
   if len(active)>=2:raise ValueError('В очереди уже есть две проверки. Отмени ненужную или дождись завершения.')
   done=sorted((j for j in self.jobs.values()if j['state']not in('queued','running')),key=lambda j:j['created'])
   for j in done[:-2]:self.jobs.pop(j['id'],None)
   ident=secrets.token_hex(12);j={'id':ident,'kind':kind,'state':'queued','created':time.monotonic(),'message':'Ожидание OpenVSP','progress':0,'events':[],'cancel':threading.Event()};self.jobs[ident]=j
   threading.Thread(target=self._run,args=(j,payload),daemon=True).start();return {'ok':True,'jobId':ident}
 def _run(self,j,payload):
  def progress(message,fraction=None,**detail):
   with self.lock:
    j['message']=message
    if fraction is not None:j['progress']=fraction
    j['events'].append({'message':message,**detail});j['events']=j['events'][-30:]
  context.cancel=j['cancel'];held=False
  try:
   deadline=time.monotonic()+300
   while not self.busy.acquire(timeout=.2):
    check_cancel()
    if time.monotonic()>deadline:raise ValueError('Не удалось дождаться OpenVSP за 300 секунд.')
   held=True;check_cancel()
   with self.lock:j['state']='running'
   result=self.runner(j['kind'],payload,progress);check_cancel()
   with self.lock:
    if j['cancel'].is_set():j.update(state='cancelled',message='Отменено; геометрия не применена')
    else:j.update(state='done',result=result,progress=1,message='Проверка завершена')
  except InterruptedError:
   with self.lock:j.update(state='cancelled',message='Отменено; геометрия не применена')
  except Exception as e:
   with self.lock:j.update(state='error',message=str(e),error=str(e))
  finally:
   if held:self.busy.release()
   context.cancel=None
 def poll(self,ident):
  with self.lock:
   if ident not in self.jobs:raise ValueError('Проверка не найдена или её результат уже освобождён.')
   return {'ok':True,**{k:v for k,v in self.jobs[ident].items()if k not in('cancel','created')}}
 def cancel(self,ident):
  with self.lock:
   if ident not in self.jobs:raise ValueError('Проверка не найдена.')
   j=self.jobs[ident];j['cancel'].set()
   if j['state']=='done':j.update(state='cancelled',message='Результат отменён');j.pop('result',None)
   return {'ok':True}
 def close(self):
  with self.lock:
   for j in self.jobs.values():
    if j['state']in('queued','running'):j['cancel'].set()
  deadline=time.monotonic()+2
  while time.monotonic()<deadline:
   with self.lock:active=any(j['state']in('queued','running')for j in self.jobs.values())
   if not active:return
   time.sleep(.02)
