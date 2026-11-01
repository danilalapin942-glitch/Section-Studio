/* Local, reversible proposals. Native verification is required for imported VSP3. */
(function(root){'use strict';
 function eligibility(project,issue,meta={}){
  if(!['pressure_station_kink','machline_inclination','machline_near_characteristic'].includes(issue?.code)||issue.body?.length!==1)return 'Эта причина риска требует ручной правки; автоматическая перестройка стыка или кромки отключена.';
  const bi=issue.body[0],body=project.bodies[bi],k=issue.station;
  if(!body?.enabled||!Number.isInteger(k)||k<1||k>=body.sections.length-1)return 'Торцевые и отсутствующие станции защищены.';
  const ss=body.sections.slice(k-1,k+2);
  if(ss.some(s=>s.shape==='point'||!s.width||!s.height))return 'Переход к точечному торцу защищён.';
  if(ss.some(s=>s.roll||s.pitch||s.yaw))return 'Ремонт повёрнутых станций требует ручной проверки.';
  const zone=[body.sections[Math.max(0,k-2)].x,body.sections[Math.min(body.sections.length-1,k+2)].x];
  if(body.sections.some(s=>(s.repairLocked||s.sharpEdge)&&s.x>=zone[0]&&s.x<=zone[1]))return 'В зоне влияния есть станция с защитой от ремонта.';
  if(body.wingFitRegion&&zone[1]>=body.wingFitRegion[0]&&zone[0]<=body.wingFitRegion[1])return 'Зона влияния пересекает защищённое сопряжение с крылом.';
  if((meta.protectedStations?.[bi]||[]).some(x=>x>=zone[0]-1e-7&&x<=zone[1]+1e-7))return 'Зона влияния пересекает станцию двигателя или связанную станцию VSP3.';
  if((project.shapeLocks||[]).some(l=>l.geomId===body.sourceId&&zone[1]>=l.x0&&zone[0]<=l.x1))return 'Зона влияния пересекает защищённую поверхность.';
  const u=root.SectionCore.knotsOf(ss[1]);
  if(ss.some(s=>s.points.length!==ss[1].points.length||root.SectionCore.knotsOf(s).some((v,j)=>Math.abs(v-u[j])>1e-8)))return 'Соседние контуры имеют разную параметризацию; их автоматическая замена небезопасна.';
  return null;
 }
 function newRisks(before,after){
  return after.issues.filter(a=>['error','warning'].includes(a.severity)&&!before.issues.some(b=>(b.code===a.code&&b.severity===a.severity||a.code==='machline_near_characteristic'&&b.code==='machline_inclination')&&b.body.join(',')===a.body.join(',')&&a.x0<=b.x1+1e-7&&a.x1>=b.x0-1e-7));
 }
 function proposeOne(project,issue,{maxMove=.05,options={},meta={}}={}){
  const C=root.SectionCore,blocked=eligibility(project,issue,meta);if(blocked)throw new Error(blocked);
  if(!Number.isFinite(maxMove)||maxMove<=0||maxMove>10)throw new Error('Предел смещения должен быть больше 0 и не больше 10 ft.');
  const bi=issue.body[0],k=issue.station,q=C.clone(project),body=q.bodies[bi],a=body.sections[k-1],s=body.sections[k],b=body.sections[k+1],t=(s.x-a.x)/(b.x-a.x);
  const target={width:(1-t)*a.width+t*b.width,height:(1-t)*a.height+t*b.height,y:(1-t)*(a.y||0)+t*(b.y||0),z:(1-t)*a.z+t*b.z};
  target.points=s.points.map((p,j)=>[(1-t)*((a.y||0)+a.width*a.points[j][0])+t*((b.y||0)+b.width*b.points[j][0]),(1-t)*(a.z+a.height*a.points[j][1])+t*(b.z+b.height*b.points[j][1])]);
  const physical=s.points.map(p=>[(s.y||0)+s.width*p[0],s.z+s.height*p[1]]),largest=Math.max(...physical.map((p,j)=>Math.hypot(p[0]-target.points[j][0],p[1]-target.points[j][1])));
  const budget=Math.min(maxMove,.05*Math.min(s.width,s.height));
  if(largest<1e-9)throw new Error('Предложение не меняет форму.');
  const mach=issue.code.startsWith('machline_'),metric=b=>mach?root.SectionMach.stationMetric(b,k,options.machline,C).inclination:root.SectionPressure.stationMetric(b,k,C).turn;
  const before=root.SectionAudit.checkGeometry(project,options,meta),oldMetric=metric(project.bodies[bi]);
  let result=null;
  // Try smaller proposals when the first one introduces a new geometric risk.
  for(const fraction of [1,.75,.5,.25]){
   // Reserve 10% for native skinning; native sampling still enforces the full limit.
   const c=C.clone(q),n=c.bodies[bi].sections[k],lambda=Math.min(1,budget*.9/largest)*fraction;
   for(const key of ['width','height','y','z'])n[key]=(1-lambda)*(s[key]||0)+lambda*target[key];
   n.points=physical.map((p,j)=>[((1-lambda)*p[0]+lambda*target.points[j][0]-n.y)/n.width,((1-lambda)*p[1]+lambda*target.points[j][1]-n.z)/n.height]);
   n.points[n.points.length-1]=n.points[0].slice();n.shape='custom';n.freeform=true;n.symmetric=!!s.symmetric||!s.freeform;
   delete n.template;delete n.wingFit;
   if(C.validate(c).length)continue;
   const after=root.SectionAudit.checkGeometry(c,options,meta),m=metric(c.bodies[bi]),introduced=newRisks(before,after);
   if(introduced.length||after.summary.errors>before.summary.errors||m>oldMetric*.95)continue;
   result={project:c,body:bi,station:k,zone:[body.sections[Math.max(0,k-2)].x,body.sections[Math.min(body.sections.length-1,k+2)].x],budget,maxMove:largest*lambda,fraction:lambda,before,after,metricBefore:oldMetric,metricAfter:m,metricKind:mach?'inclination':'turn',nativeVerified:false};break;
  }
  if(!result)throw new Error('В заданном пределе не найден ремонт, уменьшающий целевой угол хотя бы на 5% без новых рисков. Зону нужно исправить вручную.');
  return result;
 }
 function propose(project,issue,settings={}){
  const radius=Number(settings.radius||0);if(!radius)return proposeOne(project,issue,settings);
  if(!Number.isInteger(radius)||radius<1||radius>3)throw new Error('Для ремонта участка выбери от 3 до 7 станций.');
  const C=root.SectionCore,blocked=eligibility(project,issue,settings.meta||{});if(blocked)throw new Error(blocked);
  const bi=issue.body[0],b=project.bodies[bi],k=issue.station,path=C.paths(b).find(p=>p.role==='outer');
  const lo=k-radius,hi=k+radius;if(lo<=path.start||hi>=path.end)throw new Error('Выбранный участок слишком близок к торцу или границе канала. Уменьши число станций.');
  const zone=[b.sections[Math.max(path.start,lo-2)].x,b.sections[Math.min(path.end,hi+2)].x].sort((a,b)=>a-b);
  if(b.sections.some(s=>(s.repairLocked||s.sharpEdge)&&s.x>=zone[0]&&s.x<=zone[1])||b.wingFitRegion&&zone[1]>=b.wingFitRegion[0]&&zone[0]<=b.wingFitRegion[1]||(settings.meta?.protectedStations?.[bi]||[]).some(x=>x>=zone[0]&&x<=zone[1])||(project.shapeLocks||[]).some(l=>l.geomId===b.sourceId&&zone[1]>=l.x0&&zone[0]<=l.x1))throw new Error('Область влияния участка пересекает защищённую станцию, стык или зону сохранения формы.');
  const ss=b.sections.slice(lo-1,hi+2),u=C.knotsOf(ss[0]);
  if(ss.some(s=>!s.width||!s.height||s.roll||s.pitch||s.yaw||C.knotsOf(s).length!==u.length||C.knotsOf(s).some((v,j)=>Math.abs(v-u[j])>1e-8)))throw new Error('Для ремонта участка нужны ненулевые неповёрнутые станции с одинаковой параметризацией.');
  const maxMove=Number(settings.maxMove??.05);if(!Number.isFinite(maxMove)||maxMove<=0||maxMove>10)throw new Error('Проверь предел смещения.');
  const budget=Math.min(maxMove,.05*Math.min(...ss.flatMap(s=>[s.width,s.height]))),targets=[];let largest=0;
  for(let j=lo;j<=hi;j++){
   const a=b.sections[j-1],s=b.sections[j],z=b.sections[j+1],t=(s.x-a.x)/(z.x-a.x),weight=.5+.5*Math.cos(Math.PI*(j-k)/(radius+1));
   const points=s.points.map((p,n)=>{const old=C.point3(s,p),pa=C.point3(a,a.points[n]),pb=C.point3(z,z.points[n]);const desired=[old[0],(1-t)*pa[1]+t*pb[1],(1-t)*pa[2]+t*pb[2]];largest=Math.max(largest,Math.hypot(desired[1]-old[1],desired[2]-old[2])*weight);return {old,desired};});targets.push({index:j,weight,points});
  }
  if(largest<1e-9)throw new Error('Участок уже гладкий: правка не требуется.');
  const options=settings.options||{},before=root.SectionAudit.checkGeometry(project,options,settings.meta||{}),mach=issue.code.startsWith('machline_');
  const metric=body=>Math.max(...targets.map(t=>mach?root.SectionMach.stationMetric(body,t.index,options.machline,C).inclination:root.SectionPressure.stationMetric(body,t.index,C).turn));
  const oldMetric=metric(b);
  for(const fraction of [1,.75,.5,.25]){
   const q=C.clone(project),lambda=Math.min(1,budget*.9/largest)*fraction;
   for(const t of targets){const s=q.bodies[bi].sections[t.index];s.points=t.points.map(({old,desired})=>C.localPoint(s,old[1]+lambda*t.weight*(desired[1]-old[1]),old[2]+lambda*t.weight*(desired[2]-old[2])));s.points[s.points.length-1]=s.points[0].slice();s.shape='custom';s.freeform=true;s.symmetric=false;delete s.template;}
   if(C.validate(q).length)continue;const after=root.SectionAudit.checkGeometry(q,options,settings.meta||{}),next=metric(q.bodies[bi]);
   if(newRisks(before,after).length||after.summary.errors>before.summary.errors||next>oldMetric*.95)continue;
   return {project:q,body:bi,station:k,stations:targets.map(t=>t.index),zone,budget,maxMove:largest*lambda,fraction:lambda,before,after,metricBefore:oldMetric,metricAfter:next,metricKind:mach?'inclination':'turn',nativeVerified:false};
  }
  throw new Error('В заданном бюджете не найден ремонт участка без новых рисков. Исходная форма сохранена.');
 }
 const api={eligibility,propose,newRisks};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.SectionRepair=api;
})(typeof globalThis!=='undefined'?globalThis:this);
