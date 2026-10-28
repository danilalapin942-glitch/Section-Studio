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
  if(body.sections.some(s=>s.repairLocked&&s.x>=zone[0]&&s.x<=zone[1]))return 'В зоне влияния есть станция с защитой от ремонта.';
  if(body.wingFitRegion&&zone[1]>=body.wingFitRegion[0]&&zone[0]<=body.wingFitRegion[1])return 'Зона влияния пересекает защищённое сопряжение с крылом.';
  if((meta.protectedStations?.[bi]||[]).some(x=>x>=zone[0]-1e-7&&x<=zone[1]+1e-7))return 'Зона влияния пересекает станцию двигателя или связанную станцию VSP3.';
  const u=root.SectionCore.knotsOf(ss[1]);
  if(ss.some(s=>s.points.length!==ss[1].points.length||root.SectionCore.knotsOf(s).some((v,j)=>Math.abs(v-u[j])>1e-8)))return 'Соседние контуры имеют разную параметризацию; их автоматическая замена небезопасна.';
  return null;
 }
 function newRisks(before,after){
  return after.issues.filter(a=>['error','warning'].includes(a.severity)&&!before.issues.some(b=>(b.code===a.code&&b.severity===a.severity||a.code==='machline_near_characteristic'&&b.code==='machline_inclination')&&b.body.join(',')===a.body.join(',')&&a.x0<=b.x1+1e-7&&a.x1>=b.x0-1e-7));
 }
 function propose(project,issue,{maxMove=.05,options={},meta={}}={}){
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
 const api={eligibility,propose,newRisks};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.SectionRepair=api;
})(typeof globalThis!=='undefined'?globalThis:this);
