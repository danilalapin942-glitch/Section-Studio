/* Native wing sampling and reversible, local cross-section fitting. */
(function(root){
'use strict';
const C=root.SectionCore||(typeof require!=='undefined'?require('./core.js'):null);
const copy=C.clone,EPS=1e-8,mul=u=>({ft:1,m:1/.3048,mm:1/304.8,in:1/12}[u]);
function fingerprint(xml){let h=2166136261,n=0;const bytes=new TextEncoder().encode(xml);for(const b of bytes){if(b===13)continue;h=Math.imul(h^b,16777619)>>>0;n++;}return {hash:String(h),bytes:n};}
function verify(data,project){
 if(!data||data.format!=='section-studio-wing-data'||data.schema!==1||data.units!=='ft'||data.surfaceSet!=='uncapped')throw new Error('Нужен WingData.json, созданный подготовкой крыльев Section Studio.');
 const src=project.source;if(!src?.xml)throw new Error('Сначала открой исходную модель VSP3.');const fp=fingerprint(src.xml);
 if(data.sourceHash!==fp.hash||data.sourceBytes!==fp.bytes||data.sourceUnits!==src.units)throw new Error('Данные крыла относятся к другому VSP3 или другим единицам. Подготовь крыло заново из текущего исходного файла.');
 if(!Array.isArray(data.wings)||!data.wings.length||data.wings.length>64)throw new Error('В данных нет крыльев либо их слишком много.');
 const ids=new Set();let total=0;
 for(const wing of data.wings){if(typeof wing.id!=='string'||! /^[A-Za-z0-9_]{1,40}$/.test(wing.id)||ids.has(wing.id))throw new Error('Неверные идентификаторы крыльев.');ids.add(wing.id);
  if(!Array.isArray(wing.surfaces)||!wing.surfaces.length||wing.surfaces.length>16)throw new Error('Неверное число поверхностей крыла.');const seen=new Set();
  for(const s of wing.surfaces){if(!Number.isInteger(s.index)||s.index<0||seen.has(s.index))throw new Error('Неверный индекс поверхности крыла.');seen.add(s.index);
   if(!Array.isArray(s.rings)||s.rings.length<2||s.rings.length>65||s.rings.length!==wing.surfaces[0].rings?.length)throw new Error('Неверная или несогласованная выборка по размаху.');
   for(const r of s.rings){if(!Array.isArray(r)||r.length<65||r.length>1025||!r.every(p=>Array.isArray(p)&&p.length===3&&p.every(v=>Number.isFinite(v)&&Math.abs(v)<=1e5)))throw new Error('Неверные точки поверхности крыла.');total+=r.length;}
  }
 }
 if(total>1e6)throw new Error('Слишком большая выборка крыла.');
 if(root.VSPImport){const p=root.VSPImport.parse(src.xml);for(const w of data.wings)if(!p.all.some(g=>g.id===w.id&&g.type.toLowerCase()==='wing'))throw new Error('Крыло не найдено в исходном VSP3.');}
 return data;
}
function preparation(project){
 if(!project.source?.xml)throw new Error('Открой VSP3, чтобы подготовить поверхность крыла.');
 const f=mul(project.source.units);if(!f)throw new Error('Проверь единицы VSP3.');
 const script=`// Section Studio 0.8. World coordinates, actual airfoils, no aerodynamic solve.
int main(){
 file input; if(input.open("Source.vsp3","r")<0){Print("SECTION_STUDIO_ERROR: Source.vsp3 not found");return 1;}
 string xml=input.readString(input.getSize()); input.close();
 uint hash=2166136261;uint sourceBytes=0;for(uint i=0;i<xml.length();i++){if(xml[i]==13)continue;hash=(hash^uint(xml[i]))*16777619;sourceBytes++;}
 ClearVSPModel(); ReadVSPFile("Source.vsp3"); Update();
 array<string> ids=FindGeoms();file wingFile;
 if(wingFile.open("WingData.json","w")<0){Print("SECTION_STUDIO_ERROR: Cannot write WingData.json");return 1;}
 wingFile.writeString("{\\"format\\":\\"section-studio-wing-data\\",\\"schema\\":1,\\"units\\":\\"ft\\",\\"surfaceSet\\":\\"uncapped\\",\\"sourceUnits\\":\\"${project.source.units}\\",\\"sourceHash\\":\\""+hash+"\\",\\"sourceBytes\\":"+sourceBytes+",\\"wings\\":[");
 bool first=true;int count=0;
 for(uint k=0;k<ids.length();k++){
  string g=ids[k];if(GetGeomTypeName(g)!="Wing")continue;
  // End caps are omitted only in memory. The input VSP3 is never written.
  SetParmVal(g,"CapUMinOption","EndCap",NO_END_CAP);SetParmVal(g,"CapUMaxOption","EndCap",NO_END_CAP);Update();
  if(!first)wingFile.writeString(",");first=false;count++;
  wingFile.writeString("{\\"id\\":\\""+g+"\\",\\"surfaces\\":[");
  for(int s=0;s<GetTotalNumSurfs(g);s++){
   if(s>0)wingFile.writeString(",");wingFile.writeString("{\\"index\\":"+s+",\\"rings\\":[");
   for(int i=0;i<=32;i++){
    if(i>0)wingFile.writeString(",");wingFile.writeString("[");
    for(int j=0;j<=512;j++){
     if(j>0)wingFile.writeString(",");vec3d p=CompPnt01(g,s,double(i)/32.0,double(j)/512.0);
     if(p.x()!=p.x()||p.y()!=p.y()||p.z()!=p.z()||abs(p.x()*${f})>1e5||abs(p.y()*${f})>1e5||abs(p.z()*${f})>1e5){wingFile.close();Print("SECTION_STUDIO_ERROR: Non-finite or excessive wing coordinates");return 1;}
     wingFile.writeString("["+formatFloat(p.x()*${f.toPrecision(17)},"",0,15)+","+formatFloat(p.y()*${f.toPrecision(17)},"",0,15)+","+formatFloat(p.z()*${f.toPrecision(17)},"",0,15)+"]");
    }wingFile.writeString("]");
   }wingFile.writeString("]}");
  }wingFile.writeString("]}");
 }wingFile.writeString("]}");wingFile.close();
 if(GetNumTotalErrors()>0){while(GetNumTotalErrors()>0){ErrorObj e=PopLastError();Print(e.GetErrorString());}Print("SECTION_STUDIO_ERROR");return 1;}
 if(count==0){Print("SECTION_STUDIO_ERROR: No Wing components");return 1;}
 Print("SECTION_STUDIO_SAVED: WingData.json");return 0;
}
`;
 return root.VSPImport.zipStore({'Source.vsp3':project.source.xml,'Prepare_wings.vspscript':script,'README.txt':'Extract the ZIP. Drag Prepare_wings.vspscript onto Run_OpenVSP.bat. Select vspscript.exe from OpenVSP 3.51. In Section Studio, open WingData.json on the Wing fitting tab. Input geometry is not saved or modified. Coordinates are in feet; actual uncapped wing surfaces include component and section transformations. The JSON is tied to Source.vsp3 and its selected units.\n'});
}
function envelope(ring,x){
 const hits=[];for(let i=0;i<ring.length;i++){const a=ring[i],b=ring[(i+1)%ring.length],dx=b[0]-a[0];if(Math.abs(dx)<1e-13){if(Math.abs(x-a[0])<1e-8)hits.push(a,b);continue;}
  const t=(x-a[0])/dx;if(t>=-1e-9&&t<=1+1e-9)hits.push(a.map((v,k)=>v+Math.max(0,Math.min(1,t))*(b[k]-v)));
 }
 if(!hits.length)throw new Error('Плоскость X не пересекает выбранный профиль крыла.');
 return {upper:hits.reduce((a,b)=>b[2]>a[2]?b:a),lower:hits.reduce((a,b)=>b[2]<a[2]?b:a)};
}
function profile(project,settings){
 verify(project.wingData,project);const wing=project.wingData.wings.find(w=>w.id===settings.wingId);if(!wing)throw new Error('Выбери крыло.');
 const rIndex=Number(settings.ringIndex??0);if(!Number.isInteger(rIndex)||rIndex<0||rIndex>=wing.surfaces[0].rings.length)throw new Error('Проверь станцию по размаху.');
 const center=ring=>ring.reduce((sum,p)=>sum+p[1],0)/ring.length;
 const selected=wing.surfaces.find(s=>s.index===Number(settings.surfaceIndex??0));if(!selected)throw new Error('Выбери поверхность крыла.');
 const ring=selected.rings[rIndex],opposite=wing.surfaces.find(s=>s!==selected&&Math.abs(center(s.rings[rIndex])+center(ring))<1e-5&&s.rings[rIndex].every((p,j)=>Math.abs(p[0]-ring[j][0])<1e-5&&Math.abs(p[2]-ring[j][2])<1e-5));
 if(!opposite||Math.abs(center(ring))<.0001)throw new Error('Для двухстороннего сопряжения нужны зеркальные поверхности крыла с разнесёнными корнями. Выбери станцию вне оси симметрии.');
 const right=center(ring)>0?ring:opposite.rings[rIndex],left=center(ring)>0?opposite.rings[rIndex]:ring;
 const xs=right.map(p=>p[0]),x0=Math.min(...xs),x1=Math.max(...xs);if(x1-x0<.01)throw new Error('Недостаточная продольная хорда выбранного профиля.');
 const zs=right.map(p=>p[2]);if(Math.max(...zs)-Math.min(...zs)>(x1-x0)*.65)throw new Error('Поверхность слишком наклонена: этот режим рассчитан на крыло, близкое к горизонтальному.');
 return {right,left,x0,x1,chord:x1-x0,wingId:wing.id,ringIndex:rIndex};
}
const mix=(a,b,t)=>a.map((v,k)=>v+(b[k]-v)*t);
function segments(s,a,b){
 const breaks=[...new Set([...C.knotsOf(s).filter((_,i)=>i%3===0),a,b].map(x=>Number(x.toFixed(12))))].sort((a,b)=>a-b),ref=C.refine(s,breaks),out=[];
 for(let i=0;i<breaks.length-1;i++)if(breaks[i]>=a-1e-10&&breaks[i+1]<=b+1e-10)out.push({u0:breaks[i],u1:breaks[i+1],p:ref.points.slice(3*i,3*i+4).map(p=>C.point3(s,p).slice(1))});return out;
}
function point(s,u){return C.point3(s,C.curve(s.points,u,s.knots)).slice(1);}
function straight(a,b,u0,u1){return {u0,u1,p:[a,mix(a,b,1/3),mix(a,b,2/3),b]};}
function shoulder(a,b,u0,u1,start,end){
 const d=Math.hypot(b[0]-a[0],b[1]-a[1])*.3,norm=v=>{const n=Math.hypot(...v)||1;return v.map(x=>x/n);},v=norm(start),w=norm(end);
 const bounded=t=>{let h=d;for(let k=0;k<2;k++)if(Math.abs(t[k])>1e-7){const delta=b[k]-a[k];if(delta*t[k]<=0)h=0;else h=Math.min(h,Math.abs(delta/t[k])*.45);}return h;},hs=bounded(v),he=bounded(w);
 return {u0,u1,p:[a,a.map((x,k)=>x+v[k]*hs),b.map((x,k)=>x-w[k]*he),b]};
}
function tangent(s,u,side='both'){const a=point(s,Math.max(0,u-(side==='after'?0:1e-6))),b=point(s,Math.min(1,u+(side==='before'?0:1e-6)));return b.map((v,k)=>v-a[k]);}
function makeSection(s,pr,x,mode,gap,weight=1){
 const ex=Math.max(pr.x0,Math.min(pr.x1,x)),r=envelope(pr.right,ex),l=envelope(pr.left,ex),R=point(s,0),L=point(s,.5);
 const upperR=[r.upper[1]-gap,r.upper[2]],upperL=[l.upper[1]+gap,l.upper[2]],lowerR=[r.lower[1]-gap,r.lower[2]],lowerL=[l.lower[1]+gap,l.lower[2]];
 if(upperR[0]<=upperL[0]+.002||lowerR[0]<=lowerL[0]+.002)throw new Error('Зазор больше доступной ширины стыка.');
 const sampled=C.ring(s,128),lo=Math.min(...sampled.map(p=>p[2])),hi=Math.max(...sampled.map(p=>p[2]));let seg=[];
 if(mode==='high'){
  if(Math.min(upperR[1],upperL[1])<=Math.max(R[1],L[1])+.00001)throw new Error('Высокоплан: верх профиля ниже боковой средней части корпуса. Проверь компоновку и положение крыла.');
  seg=[...segments(s,0,.5),shoulder(L,upperL,.5,.625,tangent(s,.5,'before'),[0,1]),straight(upperL,upperR,.625,.875),shoulder(upperR,R,.875,1,[0,-1],tangent(s,0,'after'))];
 }else if(mode==='low'){
  if(Math.max(lowerR[1],lowerL[1])>=Math.min(R[1],L[1])-.00001)throw new Error('Низкоплан: низ профиля выше боковой средней части корпуса. Проверь компоновку и положение крыла.');
  seg=[shoulder(R,lowerR,0,.125,tangent(s,1,'before'),[0,-1]),straight(lowerR,lowerL,.125,.375),shoulder(lowerL,L,.375,.5,[0,1],tangent(s,.5,'after')),...segments(s,.5,1)];
 }else if(mode==='mid'){
  if(Math.max(r.upper[2],l.upper[2])>=hi-.00001||Math.min(r.lower[2],l.lower[2])<=lo+.00001)throw new Error('Среднеплан: профиль должен находиться между верхом и низом корпуса. Проверь компоновку.');
  const mr=mix(upperR,lowerR,.5),ml=mix(upperL,lowerL,.5),br=point(s,.125),bl=point(s,.375),tl=point(s,.625),tr=point(s,.875);
  seg=[straight(mr,lowerR,0,.0625),shoulder(lowerR,br,.0625,.125,[0,-1],tangent(s,.125)),...segments(s,.125,.375),shoulder(bl,lowerL,.375,.4375,tangent(s,.375),[0,1]),straight(lowerL,ml,.4375,.5),straight(ml,upperL,.5,.5625),shoulder(upperL,tl,.5625,.625,[0,1],tangent(s,.625)),...segments(s,.625,.875),shoulder(tr,upperR,.875,.9375,tangent(s,.875),[0,-1]),straight(upperR,mr,.9375,1)];
 }else throw new Error('Выбери высокоплан, среднеплан или низкоплан.');
 const original=segments(s,0,1),breaks=[...new Set([0,1,...original.flatMap(q=>[q.u0,q.u1]),...seg.flatMap(q=>[q.u0,q.u1])])].sort((a,b)=>a-b);
 // Bring both contours to identical Bezier partitions before blending controls.
 const pseudo={...s,points:seg.flatMap(q=>q.p.slice(0,3).map(p=>C.localPoint(s,...p))).concat([C.localPoint(s,...seg.at(-1).p[3])]),knots:seg.flatMap(q=>[q.u0,q.u0+(q.u1-q.u0)/3,q.u0+2*(q.u1-q.u0)/3]).concat([1])};
 const oldCurve=C.refine(s,breaks),newCurve=C.refine(pseudo,breaks),points=oldCurve.points.map((p,i)=>mix(p,newCurve.points[i],weight)),knots=oldCurve.knots;
 points[points.length-1]=points[0].slice();const result={...copy(s),shape:'custom',points,knots,freeform:true,symmetric:false};delete result.template;return result;
}
function rootGap(pr,s,x){
 let minimum=Infinity;const ring=C.ring(s,256);
 for(const [foil,sign] of [[pr.right,1],[pr.left,-1]]){const {lower:l,upper:u}=envelope(foil,x),lo=l[2],hi=u[2];
  for(let i=0;i<ring.length-1;i++){const a=ring[i],b=ring[i+1],dz=b[2]-a[2];let t0=0,t1=1;
   if(Math.abs(dz)>1e-12){const aa=(lo-a[2])/dz,bb=(hi-a[2])/dz;t0=Math.max(0,Math.min(aa,bb));t1=Math.min(1,Math.max(aa,bb));}else if(a[2]<lo-1e-8||a[2]>hi+1e-8)continue;
   if(t0>t1+1e-8)continue;for(const t of [t0,t1]){const z=a[2]+dz*t,y=a[1]+(b[1]-a[1])*t,fy=hi-lo>1e-12?l[1]+(u[1]-l[1])*(z-lo)/(hi-lo):(u[1]+l[1])/2;minimum=Math.min(minimum,sign*(fy-y));}
  }
 }return minimum;
}
function fit(project,settings){
 const pr=profile(project,settings),bodyIndex=Number(settings.bodyIndex),b=project.bodies[bodyIndex],gap=Number(settings.gap),transition=Number(settings.transition),count=Number(settings.stations??15);
 if(!b?.enabled)throw new Error('Выбери включённый корпус.');if(b.mirrorY||b.sections.some(s=>Math.abs(s.y||0)>1e-7||Math.abs(s.pitch||0)>1e-7||Math.abs(s.yaw||0)>1e-7))throw new Error('Сопряжение сейчас поддерживает корпус на плоскости XZ без наклона станций и зеркальных копий тела.');
 if(!Number.isFinite(gap)||gap<0||gap>pr.chord)throw new Error('Зазор должен быть положительным или нулевым и меньше хорды.');
 if(!Number.isFinite(transition)||transition<.01||transition>pr.chord*2)throw new Error('Длина перехода должна быть от 0,01 ft до двух хорд.');
 if(!Number.isInteger(count)||count<7||count>25)throw new Error('Нужно от 7 до 25 станций по хорде.');
 const x0=pr.x0-transition,x1=pr.x1+transition;if(x0<=b.sections[0].x+.001||x1>=b.sections.at(-1).x-.001)throw new Error('Зона стыка с переходами должна находиться внутри длины корпуса. Уменьши переход.');
 const original=copy(b),q=copy(project),target=q.bodies[bodyIndex];
 const positions=[x0,pr.x0-transition*.5,pr.x0-transition*.25,...Array.from({length:count},(_,i)=>pr.x0+pr.chord*(1-Math.cos(Math.PI*i/(count-1)))/2),pr.x1+transition*.25,pr.x1+transition*.5,x1];
 for(const x of positions){if(target.sections.some(s=>Math.abs(s.x-x)<.001))continue;C.addAt(target,x);}
 let changed=0;for(let i=0;i<target.sections.length;i++){const s=target.sections[i];if(s.x<x0+1e-8||s.x>x1-1e-8)continue;
  const old=C.sectionAt(original,s.x)?.section;if(!old?.width)throw new Error('В зоне стыка найдено точечное сечение.');
  const t=s.x<pr.x0?(s.x-x0)/transition:s.x>pr.x1?(x1-s.x)/transition:1,weight=t*t*t*(10+t*(-15+6*t));
  if(weight<EPS)continue;
  const fitted=makeSection(old,pr,s.x,settings.mode,gap,weight);fitted.x=s.x;if(s.sourceId)fitted.sourceId=s.sourceId;
  fitted.wingFit={wingId:pr.wingId,mode:settings.mode,gapFt:gap,ringIndex:pr.ringIndex};target.sections[i]=fitted;changed++;
 }
 target.wingFitRegion=[x0,x1];
 const errors=C.validate(q);if(errors.length)throw new Error('Подгонка создаёт непригодный контур: '+errors[0]);
 // Test the preview between native stations too; export still needs native inspection.
 for(let i=0;i<=40;i++){const s=C.sectionAt(target,x0+(x1-x0)*i/40).section;const e=C.validateBody({...target,sections:[{...s,x:0},{...s,x:1},{...s,x:2}]});if(e.length)throw new Error('Промежуточное сечение пересекается. Уменьши подгонку или измени исходную форму корпуса.');}
 let previewMinGapYFt=Infinity;for(let i=0;i<=128;i++){const x=pr.x0+pr.chord*i/128;previewMinGapYFt=Math.min(previewMinGapYFt,rootGap(pr,C.sectionAt(target,x).section,x));}
 if(previewMinGapYFt<-1e-5)throw new Error('Корпус выходит внутрь корневой зоны крыла по предварительной выборке. Измени исходные сечения или параметры стыка.');
 if(!Number.isFinite(previewMinGapYFt))throw new Error('Не удалось проверить корневой стык по всей хорде.');
 const report={bodyIndex,wingId:pr.wingId,mode:settings.mode,x0:pr.x0,x1:pr.x1,region:[x0,x1],gapFt:gap,transitionFt:transition,added:target.sections.length-original.sections.length,changed,total:target.sections.length,stationOnly:true,previewMinGapYFt,rootClearanceSamplePlanes:129};
 q.lastWingFit=report;return {project:q,report,profile:pr};
}
function suggested(project,wingId,selection={}){
 const wing=project.wingData.wings.find(w=>w.id===wingId)||project.wingData.wings[0],settings={wingId:wing.id,bodyIndex:0,surfaceIndex:wing.surfaces[0].index,ringIndex:0,...selection};const pr=profile(project,settings),s=C.sectionAt(project.bodies[settings.bodyIndex],(pr.x0+pr.x1)/2)?.section;if(!s)return {...settings,mode:'high',gap:.001,transition:pr.chord*.12,stations:15};
 const env=envelope(pr.right,(pr.x0+pr.x1)/2),rr=C.ring(s,128),top=Math.max(...rr.map(p=>p[2])),bottom=Math.min(...rr.map(p=>p[2])),z=(env.upper[2]+env.lower[2])/2;
 return {...settings,mode:z>s.z+s.height*.23?'high':z<s.z-s.height*.23?'low':'mid',gap:Math.max(0,env.upper[1]-Math.max(...rr.map(p=>p[1]))),transition:pr.chord*.12,stations:15,bodyTop:top,bodyBottom:bottom};
}
const api={fingerprint,verify,preparation,envelope,profile,fit,suggested,makeSection,rootGap};root.WingFit=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
