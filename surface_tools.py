"""Native parameter layout validation, semantic TRI patches and seam smoothness.

No flow solver is run. Roles are accepted only when candidate native rib
parameters agree with the planes of the source section IDs.
"""
import itertools,math
from spatial_geometry import sub,dot,triangle_area

NATIVE_SEMANTICS=r'''
 uint gridPoints=0,probeRows=0;file grid;grid.open("NativeGrid.txt","w");file probes;probes.open("LayoutProbes.txt","w");file ranges;ranges.open("NativeRanges.txt","w");
 for(uint k=0;k<ids.length();k++){
  string g=ids[k];if(GetGeomTypeName(g)!="Fuselage")continue;
  int ns=GetTotalNumSurfs(g),nx=GetNumXSec(GetXSecSurf(g,0));
  for(int s=0;s<ns;s++){
   array<double> us,ws;GetUWTess01(g,s,us,ws);
   gridPoints+=us.length()*ws.length();if(gridPoints>1000000||us.length()*ws.length()>250000){Print("SECTION_STUDIO_ERROR: Native semantic grid limit.");return 1;}
   grid.writeString(g+" "+s+" "+us.length()+" "+ws.length()+"\n");
   for(uint i=0;i<us.length();i++)for(uint j=0;j<ws.length();j++){
    vec3d p=CompPnt01(g,s,us[i],ws[j]);grid.writeString(formatFloat(us[i],"",0,15)+" "+formatFloat(p.x(),"",0,15)+" "+formatFloat(p.y(),"",0,15)+" "+formatFloat(p.z(),"",0,15)+"\n");
   }
  }
  // GeomEngine trims the original source parameter before adding cap patches.
  // Lip/face indices below are read back from the active native engine state.
  int io=int(GetParmVal(g,"GeomIOType","EngineModel")),it=int(GetParmVal(g,"GeomInType","EngineModel")),ot=int(GetParmVal(g,"GeomOutType","EngineModel")),im=int(GetParmVal(g,"InletModeType","EngineModel")),om=int(GetParmVal(g,"OutletModeType","EngineModel"));
  double start=0,finish=nx-1,inface=GetParmVal(g,"InletFaceU","EngineModel")*(nx-1),inlip=GetParmVal(g,"InletLipU","EngineModel")*(nx-1),outface=GetParmVal(g,"OutletFaceU","EngineModel")*(nx-1),outlip=GetParmVal(g,"OutletLipU","EngineModel")*(nx-1);
  bool supported=true,flowpath=it==1||ot==1;
  if(io!=0){
   if((io<=2&&im>=5)||(io>=2&&om>=5)||(io==2&&(im==1||im==2))||(io==2&&it==0&&abs(inface)>1e-9))supported=false;
   if(flowpath){if(io==2){if(im==3)start=inlip;if(om==3)finish=outlip;}}
   else if(!(io==2&&im==0)){if(io<=2){if(im==3)start=inlip;else if(im==4)start=inface;}if(io>=2){if(om==3)finish=outlip;else if(om==4)finish=outface;}}
  }
  if(finish-start<1e-8){supported=false;start=0;finish=nx-1;}
  ranges.writeString(g+" "+formatFloat(start,"",0,15)+" "+formatFloat(finish,"",0,15)+" "+(supported?"1":"0")+"\n");
  if(!supported)continue;
  for(int front=0;front<=2;front++)for(int back=0;back<=2;back++){
   double den=finish-start+front+back;
   for(int i=0;i<nx;i++){
    if(i<start-1e-9||i>finish+1e-9)continue;
    probeRows++;if(probeRows>100000){Print("SECTION_STUDIO_ERROR: Native probe limit.");return 1;}double u=(i-start+front)/den,d=0.0001/den,jump=0,curvature=0;
    probes.writeString(g+" "+front+" "+back+" "+i);
    for(int j=0;j<4;j++){vec3d p=CompPnt01(g,0,u,double(j)/4);probes.writeString(" "+formatFloat(p.x(),"",0,15)+" "+formatFloat(p.y(),"",0,15)+" "+formatFloat(p.z(),"",0,15));}
    if(i>start+1e-9&&i<finish-1e-9)for(int j=0;j<16;j++){
     double w=double(j)/16;vec3d l=CompNorm01(g,0,u-d,w),r=CompNorm01(g,0,u+d,w),ll=CompNorm01(g,0,u-2*d,w),rr=CompNorm01(g,0,u+2*d,w);
     double mm=l.mag()*r.mag();if(mm>1e-15){double c=dot(l,r)/mm;if(c>1)c=1;if(c< -1)c=-1;double a=acos(c)*180/3.141592653589793;if(a>jump)jump=a;}
     vec3d pl=CompPnt01(g,0,u-d,w),pr=CompPnt01(g,0,u+d,w),pll=CompPnt01(g,0,u-2*d,w),prr=CompPnt01(g,0,u+2*d,w);
     double dl=dist(pl,pll),dr=dist(pr,prr);if(dl>1e-10&&dr>1e-10){double z=abs((l-ll).mag()/dl-(r-rr).mag()/dr);if(z>curvature)curvature=z;}
    }
    probes.writeString(" "+formatFloat(jump,"",0,15)+" "+formatFloat(curvature,"",0,15)+"\n");
   }
  }
 }
 grid.close();probes.close();ranges.close();
'''

def branches(sections):
 xs=[s['localX']for s in sections];runs=[];start=0;direction=0
 for i in range(1,len(xs)):
  d=1 if xs[i]>xs[i-1]+1e-10 else -1 if xs[i]<xs[i-1]-1e-10 else 0
  if d and direction and d!=direction:runs.append((start,i-1));start=i-1
  if d:direction=d
 runs.append((start,len(xs)-1));outer=max(runs,key=lambda t:abs(xs[t[1]]-xs[t[0]]))
 return runs,outer

def read_semantics(folder,meta,mesh,factor):
 probes={};ranges={}
 if(folder/'NativeRanges.txt').exists():
  for line in(folder/'NativeRanges.txt').read_text(encoding='utf-8').splitlines():
   gid,lo,hi,ok=line.split();lo,hi=float(lo),float(hi)
   if gid not in meta or not all(math.isfinite(x)for x in(lo,hi))or not 0<=lo<hi<=len(meta[gid]['sections'])-1:raise ValueError('Неверный нативный диапазон станций.')
   ranges[gid]={'start':lo,'end':hi,'supported':ok=='1'}
 for line in(folder/'LayoutProbes.txt').read_text(encoding='utf-8').splitlines():
  a=line.split();gid=a[0];front,back,i=map(int,a[1:4]);v=list(map(float,a[4:]));m=meta[gid];s=m['sections'][i]
  if len(v)!=14 or not all(math.isfinite(x)for x in v):raise ValueError('Нативная проверка параметризации вернула нечисловые значения.')
  points=[tuple(v[3*j+k]*factor for k in range(3))for j in range(4)]
  endpoint_point=s.get('curveType')==0 and i in(0,len(m['sections'])-1)
  residual=0. if endpoint_point else max(abs(dot(sub(p,s['center']),s['normal']))for p in points)
  probes.setdefault(gid,{}).setdefault((front,back),[]).append({'i':i,'planeResidualFt':residual,'nativePointClosure':endpoint_point,'normalJumpDeg':v[12],'curvatureJumpPerFt':v[13]/factor})
 layouts={}
 for gid,poss in probes.items():
  ranked=sorted((max(x['planeResidualFt']for x in rows),caps,rows)for caps,rows in poss.items())
  residual,caps,rows=ranked[0];valid=residual<=1e-6
  anchors=sum(not row.get('nativePointClosure')for row in rows)
  if anchors<2:valid=False
  # Distinct cap hypotheses must not both fit; ambiguous layouts stay unassigned.
  if len(ranked)>1 and ranked[1][0]<=1e-6:valid=False
  runs,outer=branches(meta[gid]['sections'])
  visible=ranges.get(gid,{'start':0.,'end':float(len(meta[gid]['sections'])-1),'supported':True})
  layouts[gid]={'verified':valid,'frontCaps':caps[0],'backCaps':caps[1],'maximumPlaneResidualFt':residual,'validatedPlaneCount':anchors,'sourceRange':visible,'sectionIds':[s['id']for s in meta[gid]['sections']],'outer':outer,'runs':runs,'stations':rows}
  if not valid:layouts[gid]['reason']='Параметры исходных сечений не сопоставлены однозначно с нативной поверхностью. Возможны обрезка двигателя или недостаточное число опорных плоскостей; авторазметка и контроль плавности этого корпуса не подтверждены.'
 for gid,visible in ranges.items():
  if gid not in layouts:layouts[gid]={'verified':False,'sourceRange':visible,'stations':[],'reason':'Отрицательные дополнительные поверхности, удлинение или поворот интегрального тракта пока не сопоставляются автоматически. Исходная геометрия сохраняется; категории и плавность требуют отдельной проверки.'}
 def role(gid,u):
  l=layouts[gid];m=meta[gid];n=len(m['sections']);visible=l['sourceRange'];x=u*(visible['end']-visible['start']+l['frontCaps']+l['backCaps'])-l['frontCaps']+visible['start']
  if x<visible['start']-1e-8:return 'flow-face-closure'if m['engineIO']in(1,2)else'external'
  if x>visible['end']+1e-8:return 'flow-face-closure'if m['engineIO']in(2,3)else'external'
  i=min(n-2,max(0,int(math.floor(x+1e-8))))
  return 'external'if l['outer'][0]<=i<l['outer'][1]else'internal-duct'
 def vertex(p):return tuple(round(v,5)for v in p)
 def facekey(t):return tuple(sorted(vertex(p)for p in t))
 native={};vertices={}
 with(folder/'NativeGrid.txt').open(encoding='utf-8')as f:
  while line:=f.readline():
   gid,si,nu,nw=line.split();nu,nw=int(nu),int(nw);rows=[];us=[]
   for i in range(nu):
    row=[]
    for j in range(nw):
     v=list(map(float,f.readline().split()));row.append(tuple(x*factor for x in v[1:]));u=v[0]
    rows.append(row);us.append(u)
    if layouts.get(gid,{}).get('verified'):
     for point in row:vertices.setdefault((gid,tuple(math.floor(v/1e-5)for v in point)),[]).append((point,u))
   if not layouts.get(gid,{}).get('verified'):continue
   for i in range(nu-1):
    for j in range(nw-1):
     corners=[rows[i][j],rows[i+1][j],rows[i+1][j+1],rows[i][j+1]];uv=[us[i],us[i+1],us[i+1],us[i]]
     for indices in itertools.combinations(range(4),3):
      t=[corners[k]for k in indices]
      if triangle_area(t)<=1e-18:continue
      key=(gid,facekey(t));r=role(gid,sum(uv[k]for k in indices)/3)
      if key in native and native[key]!=r:native[key]=None
      else:native[key]=r
 labels={};unknown=[];parts=mesh['parts']
 for i,(face,part)in enumerate(zip(mesh['faces'],mesh['faceParts'])):
  gid=parts[part]['geomId'];r=native.get((gid,facekey([mesh['nodes'][j]for j in face])))
  if r is None and layouts.get(gid,{}).get('verified'):
   candidates=[]
   for index in face:
    point=mesh['nodes'][index];key=tuple(math.floor(v/1e-5)for v in point);hits=[]
    for delta in itertools.product((-1,0,1),repeat=3):
     for native_point,u in vertices.get((gid,tuple(key[k]+delta[k]for k in range(3))),[]):
      if math.dist(point,native_point)<2.5e-6:hits.append(u)
    if not hits:break
    candidates.append((min(hits),max(hits)))
   if len(candidates)==3:
    roles={role(gid,sum(us)/3)for us in itertools.product(*candidates)}
    if len(roles)==1:r=roles.pop()
  if meta[gid]['type']=='Wing':r='external'
  if r:labels[str(i)]=r
  else:unknown.append(i)
 return {'method':'native-rib-plane-validated-parameters','layouts':layouts,'faces':labels,'classifiedFaces':len(labels),'unknownFaces':len(unknown),'firstUnknownFaces':unknown[:50],'coverage':len(labels)/max(1,len(mesh['faces'])),'complete':not unknown,'note':'Авторазметка подтверждена плоскостями исходных ID сечений и нативной параметризацией. Нераспознанные грани требуют ручной категории; топологическая роль не доказывает отсутствие перекрытий.'}

def smoothness(semantics,meta,intended=(),angle=5.,curvature=2.):
 ignored={(x['geomId'],x['stationId'])for x in intended if isinstance(x,dict)and 'geomId'in x and 'stationId'in x};out=[]
 for gid,layout in semantics.get('layouts',{}).items():
  if not layout['verified']:continue
  for row in layout['stations']:
   i=row['i'];sid=meta[gid]['sections'][i]['id']
   visible=layout.get('sourceRange',{'start':0,'end':len(meta[gid]['sections'])-1})
   if not max(layout['outer'][0],visible['start'])<i<min(layout['outer'][1],visible['end']):continue
   intentional=(gid,sid)in ignored;bad=row['normalJumpDeg']>angle or row['curvatureJumpPerFt']>curvature
   out.append({'geomId':gid,'name':meta[gid]['name'],'stationId':sid,'station':i,'point':meta[gid]['sections'][i]['center'],'normalJumpDeg':row['normalJumpDeg'],'curvatureJumpPerFt':row['curvatureJumpPerFt'],'intentionalEdge':intentional,'warning':bad and not intentional})
 return {'method':'native-one-sided-normals-and-finite-curvature','stations':out,'warnings':sum(x['warning']for x in out),'complete':all(x['verified']for x in semantics.get('layouts',{}).values()),'angleThresholdDeg':angle,'curvatureThresholdPerFt':curvature,'note':'Пороги — настройки геометрического контроля. Кривизна оценена по односторонним конечным разностям нормалей; это не критерий Cp или сертификация C2.'}
