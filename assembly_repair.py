"""Bounded multi-junction repair driven by actual native TRI clearances.

Only controls of permitted outer FUSELAGE stations move. Wing, section X,
engine stations, internal paths and user protected stations are immutable.
Every accepted result is read back and checked natively before it is offered.
"""
import copy,math,xml.etree.ElementTree as ET
from assembly_audit import assembly,compare,describe,safe_pairs
from geometry_frames import val,local,vector,matrix,section_plane,frame_of,world
from native_audit import FACTORS
from native_control import check_cancel
from surface_tools import branches

def score(report):
 total=0.
 for p in report['pairs']:
  if not p['complete']or p['distanceFt']is None:return math.inf
  short=max(0.,p['minimumGapFt']-p['toleranceFt']-p['distanceFt'])/max(p['minimumGapFt'],.001)
  total+=short*short+(10 if p['state']=='contact'else 100 if p['state']=='overlap'else 0)
 return total

def source_sections(root,gid):
 g=next(g for g in root.findall('./Vehicle/Geom')if g.findtext('ParmContainer/ID')==gid)
 return g,g.findall('FuselageGeom/XSecSurf/XSec')

def put(node,path,v):
 e=node.find(path)
 if e is None:raise ValueError('В исходном сечении нет параметра '+path)
 e.set('Value',format(v,'.17g'))

def dimensions(xs):
 curve=xs.find('XSec/XSecCurve');kind=int(curve.findtext('XSecCurve/Type','-1'));pc=curve.find('ParmContainer/XSecCurve')
 def field(name):return next((e for e in pc if e.tag==name or e.tag.endswith('_'+name)),None)if pc is not None else None
 if kind==1:
  d=field('Diameter');return kind,pc,d,d,float(d.get('Value')),float(d.get('Value'))
 w,h=field('Width'),field('Height');return kind,pc,w,h,float(w.get('Value'))if w is not None else 0.,float(h.get('Value'))if h is not None else 0.

def change_surface(xml,pair,gid,step,sign,zone,protected,units,geoms):
 factor=FACTORS[units];root=ET.fromstring(xml);g,ss=source_sections(root,gid);frame=frame_of(g,factor);meta=describe(xml,factor)[gid]
 if len(ss)<3:return None
 _,outer=branches(meta['sections']);which='A'if pair['a']==gid else'B';p=pair['point'+which];other=pair['point'+('B'if which=='A'else'A')]
 if p is None or other is None:return None
 delta=tuple(p[k]-other[k]for k in range(3));length=math.sqrt(sum(v*v for v in delta))
 if length<1e-9:
  # Contact has no unique distance gradient. Try both signs of a native face
  # normal; a later native score decides whether either proposal helps.
  delta=tuple(pair.get('normal'+which)or(0,1,0));length=math.sqrt(sum(v*v for v in delta))
 gradient=tuple(sign*v/length for v in delta)
 if meta['symmetry']==2:
  reflected=(p[0],-p[1],p[2]);centers=[s['center']for s in meta['sections']]
  if min(math.dist(reflected,c)for c in centers)<min(math.dist(p,c)for c in centers):p=reflected;gradient=(gradient[0],-gradient[1],gradient[2])
 point=local(frame,p);local_gradient=vector(frame,gradient,True)
 engine=set()
 for side,enabled in [('Inlet',meta['engineIO']in(1,2)),('Outlet',meta['engineIO']in(2,3))]:
  if enabled:
   for key in ['Face','Lip']:
    stem='ParmContainer/EngineModel/'+side+key
    if val(g,stem+'Mode')==1:
     index=val(g,stem+'U')*(len(ss)-1)
     # A between-rib engine trim depends on the whole adjacent skin. Leave
     # that body to manual editing until a dedicated trim guard is available.
     if abs(index-round(index))>1e-7:return None
     engine.add(int(round(index)))
    else:engine.add(int(val(g,stem+'Index')))
 allowed=[]
 for i in range(outer[0]+1,outer[1]):
  sid=meta['sections'][i]['id'];x=meta['sections'][i]['center'][0]
  if i in engine or sid in protected or not zone[0]<=x<=zone[1]:continue
  kind,_,_,_,w,h=dimensions(ss[i])
  if kind in(1,2,11)and w>0 and h>0:allowed.append(i)
 if not allowed:return None
 near=sorted(allowed,key=lambda i:abs(meta['sections'][i]['localX']-point[0]))[:7]
 spacing=max(.05,min((abs(meta['sections'][i]['localX']-meta['sections'][j]['localX'])for i in near for j in near if i!=j and abs(meta['sections'][i]['localX']-meta['sections'][j]['localX'])>1e-6),default=.5))
 axial=max(spacing*2.5,.1);changed=[]
 for i in near:
  xs=ss[i];sx=meta['sections'][i]['localX'];weight=math.exp(-.5*((sx-point[0])/axial)**2)
  if weight<.002:continue
  rot=matrix([val(xs,'ParmContainer/XSec/'+k+'Rotate')for k in 'XYZ']);v=tuple(sum(rot[j][k]*local_gradient[j]for j in range(3))for k in range(3));projection=v[1]*v[1]+v[2]*v[2]
  if projection<.0025:continue
  dy,dz=v[1]*step*weight/projection/factor,v[2]*step*weight/projection/factor
  kind,pc,we,he,w,h=dimensions(xs)
  if kind==11:
   if int(val(xs,'XSec/XSecCurve/ParmContainer/XSecCurve/AbsoluteFlag'))!=0:return None
   n=int(xs.findtext('XSec/XSecCurve/EditCurveXSec/NumPts','0'));center=[val(xs,'ParmContainer/XSec/'+k+'LocPercent')*frame['length']for k in 'XYZ'];offset=tuple(point[k]-center[k]for k in range(3));psec=tuple(sum(rot[j][k]*offset[j]for j in range(3))/factor for k in range(3));radius=max(.05/factor,.3*min(w,h))
   values=[]
   for j in range(n):
    ex,ey=pc.find('X_'+str(j)),pc.find('Y_'+str(j));x,y=float(ex.get('Value')),float(ey.get('Value'));radial=math.exp(-.5*((w*x-psec[1])**2+(h*y-psec[2])**2)/radius**2);values.append((ex,ey,x+dy*radial/w,y+dz*radial/h))
   for ex,ey,x,y in values:ex.set('Value',format(x,'.17g'));ey.set('Value',format(y,'.17g'))
   if pc.find('SymType')is not None:pc.find('SymType').set('Value','0')
   for axis in ['X','Y']:pc.find(axis+'_'+str(n-1)).set('Value',pc.find(axis+'_0').get('Value'))
  elif kind==1:
   # A circle supports symmetric radial contraction only; verification must
   # show that this proposal actually increases the selected clearance.
   new=max(.001/factor,w-2*math.hypot(dy,dz));we.set('Value',format(new,'.17g'))
  else:
   if abs(dy)>1e-15:we.set('Value',format(max(.001/factor,w-2*abs(dy)),'.17g'))
   if abs(dz)>1e-15:he.set('Value',format(max(.001/factor,h-2*abs(dz)),'.17g'))
  changed.append(meta['sections'][i]['id'])
 if not changed:return None
 bounds=geoms(xml)[gid][1];out=xml[:bounds[0]]+ET.tostring(g,encoding='unicode')+xml[bounds[1]:]
 return out,changed

def control_bound(original,current,units):
 factor=FACTORS[units];a,b=ET.fromstring(original),ET.fromstring(current);maximum=0.
 for ga in a.findall('./Vehicle/Geom'):
  gid=ga.findtext('ParmContainer/ID');gb,ssb=source_sections(b,gid);ssa=ga.findall('FuselageGeom/XSecSurf/XSec')
  if not ssa:continue
  for x,y in zip(ssa,ssb):
   kind,pc,_,_,w,h=dimensions(x);_,qc,_,_,ww,hh=dimensions(y)
   if kind==11:
    n=int(x.findtext('XSec/XSecCurve/EditCurveXSec/NumPts','0'))
    for i in range(n):
     d=math.hypot(w*float(pc.find('X_'+str(i)).get('Value'))-ww*float(qc.find('X_'+str(i)).get('Value')),h*float(pc.find('Y_'+str(i)).get('Value'))-hh*float(qc.find('Y_'+str(i)).get('Value')))*factor;maximum=max(maximum,d)
   else:maximum=max(maximum,.5*math.hypot(w-ww,h-hh)*factor)
 return maximum

def repair_assembly(executable,root,data,geoms,progress=lambda *a,**k:None):
 xml=data['xml'];units=data['units'];meta=describe(xml,FACTORS[units]);pairs=safe_pairs(data.get('pairs'),meta);mutable=data.get('mutableIds');budget=data.get('budgetFt',.05);zone=data.get('zoneFt',[-1e6,1e6]);limit=data.get('iterations',6)
 if not isinstance(mutable,list)or not mutable or len(mutable)>32 or len(set(mutable))!=len(mutable)or any(g not in meta or meta[g]['type']!='Fuselage'for g in mutable):raise ValueError('Выбери от 1 до 32 изменяемых FUSELAGE; Wing остаётся опорным.')
 if isinstance(budget,bool)or not isinstance(budget,(int,float))or not math.isfinite(budget)or not .00001<=budget<=1:raise ValueError('Бюджет ремонта должен быть от 0,00001 до 1 ft.')
 if not isinstance(zone,list)or len(zone)!=2 or not all(isinstance(x,(int,float))and math.isfinite(x)for x in zone)or zone[1]<=zone[0]:raise ValueError('Проверь границы зоны ремонта.')
 if not isinstance(limit,int)or isinstance(limit,bool)or not 1<=limit<=12:raise ValueError('Допустимо от 1 до 12 итераций.')
 protected=data.get('protectedStations',[])
 if not isinstance(protected,list)or len(protected)>32768 or any(not isinstance(x,str)for x in protected):raise ValueError('Неверный список защищённых станций.')
 intended=data.get('intendedEdges',[]);locks=data.get('locks',[])
 if not isinstance(locks,list)or any(not isinstance(l,dict)or l.get('geomId')not in meta or not all(isinstance(l.get(k),(int,float))and math.isfinite(l[k])for k in ['x0','x1','toleranceFt'])or l['x1']<=l['x0']or not 0<=l['toleranceFt']<=10 for l in locks):raise ValueError('Неверные зоны защиты.')
 protected=set(protected)|{e.get('stationId')for e in intended if isinstance(e,dict)}
 for gid in mutable:
  for s in meta[gid]['sections']:
   if any(l['geomId']==gid and l['x0']<=s['center'][0]<=l['x1']for l in locks):protected.add(s['id'])
 request={'units':units,'pairs':pairs,'areas':False,'semantic':True,'intendedEdges':intended}
 progress('Исходная нативная сетка и плавность переходов',.04)
 initial=assembly(executable,root,request|{'xml':xml})['report'];current=initial;state=xml;history=[];affected=set()
 if not initial['complete']:return {'ok':True,'passed':False,'reasons':['Исходная проверка неполная. Автодоводка не начата.'],'initial':initial}
 if not initial.get('smoothness',{}).get('complete',False):return {'ok':True,'passed':False,'xml':None,'reasons':['Исходная плавность переходов не проверена полностью: параметризация корпуса не сопоставлена с сечениями. Автодоводка не начата.'],'initial':initial,'report':initial}
 for gid in mutable:
  visible=initial.get('semanticSurface',{}).get('layouts',{}).get(gid,{}).get('sourceRange')
  if visible:
   for i,s in enumerate(meta[gid]['sections']):
    if i<=visible['start']+1e-9 or i>=visible['end']-1e-9:protected.add(s['id'])
 for iteration in range(limit):
  check_cancel()
  if current['passed']:break
  oldscore=score(current);best=None;issues=sorted((p for p in current['pairs']if not p['passed']),key=lambda p:p['minimumGapFt']-(p['distanceFt']or 0),reverse=True)
  for attempt,sign in enumerate([1.,-1.]):
   trial=state;changed=set()
   for pair in issues:
    candidates=[g for g in mutable if g in(pair['a'],pair['b'])]
    if not candidates:continue
    need=max(pair['minimumGapFt']+pair['toleranceFt']*.25-(pair['distanceFt']or 0),.00005);step=min(need*1.4,budget*.35)
    proposed=change_surface(trial,pair,candidates[-1],step,sign,zone,protected,units,geoms)
    if proposed:trial,ids=proposed;changed.update(ids)
   if not changed:continue
   bound=control_bound(xml,trial,units)
   if bound>budget*.95:continue
   progress(f'Итерация {iteration+1}: проверка всех {len(pairs)} стыков',.1+.65*(iteration+.5*attempt)/limit,controlBoundFt=bound)
   r=assembly(executable,root,request|{'xml':trial,'semantic':False})['report'];s=score(r)
   if s<oldscore-1e-9 and(best is None or s<best[0]):best=(s,trial,r,changed,bound)
   if r['passed']:break
  if best is None:break
  _,state,current,changed,bound=best;affected.update(changed);history.append({'iteration':iteration+1,'score':score(current),'controlBoundFt':bound,'pairs':[{k:p[k]for k in ['a','b','distanceFt','state','passed']}for p in current['pairs']]})
 progress('Уточнённая сетка и окончательные пространственные зазоры',.8)
 final=assembly(executable,root,request|{'xml':state,'refine':True,'distanceMap':True})['report'];reasons=[]
 if not final['complete']or not final['passed']:reasons.append('Все заданные зазоры в пределах бюджета получить не удалось.')
 if not initial.get('smoothness',{}).get('complete',False)or not final.get('smoothness',{}).get('complete',False):reasons.append('Плавность переходов не проверена полностью: нативная параметризация не сопоставлена с сечениями.')
 # Source locks plus the portions outside the allowed global X interval.
 for gid in mutable:
  mesh=initial['mesh'];parts={p['part']:p['geomId']for p in mesh['parts']};node_ids={i for f,t in zip(mesh['faces'],mesh['faceParts'])if parts[t]==gid for i in f};points=[mesh['nodes'][i]for i in node_ids];minimum=min(p[0]for p in points);maximum=max(p[0]for p in points)
  if zone[0]>minimum+1e-8:locks=locks+[{'geomId':gid,'x0':minimum-1e-8,'x1':zone[0]-1e-8,'toleranceFt':1e-6}]
  if zone[1]<maximum-1e-8:locks=locks+[{'geomId':gid,'x0':zone[1]+1e-8,'x1':maximum+1e-8,'toleranceFt':1e-6}]
 progress('Нативный бюджет смещения и защищённые поверхности',.9)
 preservation=compare(executable,root,{'xml':state,'originalXml':xml,'units':units,'locks':locks})['report']
 if not preservation['complete']or not preservation['locksPassed']:reasons.append('Защита формы или проверка вне зоны не пройдена.')
 for r in preservation['components']:
  if r['id']in mutable and r.get('maximumMoveFt',math.inf)>budget*1.001+1e-7:reasons.append('Нативное перемещение превысило бюджет.')
  if r['id']not in mutable and(not r['parametersUnchanged']or r.get('maximumMoveFt',math.inf)>1e-7):reasons.append('Изменился опорный компонент.')
 before={(s['geomId'],s['stationId']):s for s in initial.get('smoothness',{}).get('stations',[])};worsened=[]
 for s in final.get('smoothness',{}).get('stations',[]):
  old=before.get((s['geomId'],s['stationId']))
  if old and not s['intentionalEdge']and(s['normalJumpDeg']>max(5.,old['normalJumpDeg']+.25)or s['curvatureJumpPerFt']>max(2.,old['curvatureJumpPerFt']*1.1+.25)):worsened.append(s)
 if worsened:reasons.append('Плавность переходов ухудшилась сверх допуска.')
 passed=not reasons;progress('Результат готов к просмотру',1.,passed=passed)
 return {'ok':True,'passed':passed,'xml':state if passed else None,'initial':initial,'report':final,'preservation':preservation,'history':history,'changedStationIds':sorted(affected),'budgetFt':budget,'zoneFt':zone,'reasons':reasons,'worsenedSmoothness':worsened,'solverRun':False}
