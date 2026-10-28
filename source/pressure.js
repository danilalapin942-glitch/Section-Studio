/* Explainable pre-solve indicators. Thresholds belong to Studio, not VSPAERO. */
(function(root){'use strict';
 const clamp=x=>Math.max(-1,Math.min(1,x));
 const sub=(a,b)=>a.map((v,k)=>v-b[k]);
 const norm=a=>Math.hypot(...a);
 const angle=(a,b)=>Math.acos(clamp(a.reduce((s,v,k)=>s+v*b[k],0)/(norm(a)*norm(b)||1)))*180/Math.PI;
 function stationMetric(body,k,C=root.SectionCore){
  if(k<1||k>=body.sections.length-1)return null;
  const [a,s,b]=body.sections.slice(k-1,k+2);
  if([a,s,b].some(q=>!q.width||!q.height))return null;
  const ra=C.ring(a,64),rs=C.ring(s,64),rb=C.ring(b,64),t=(s.x-a.x)/(b.x-a.x);
  let turn=0,deviation=0,point=rs[0];
  for(let j=0;j<64;j++){
   const theta=angle(sub(rs[j],ra[j]),sub(rb[j],rs[j]));
   if(theta>turn){turn=theta;point=rs[j];}
   deviation=Math.max(deviation,norm(rs[j].map((v,d)=>v-((1-t)*ra[j][d]+t*rb[j][d]))));
  }
  return {turn,deviation,point,diameter:Math.max(s.width,s.height),x0:a.x,x1:b.x,station:k};
 }
 function scan(project,options={},C=root.SectionCore){
  const turnLimit=Number(options.pressureTurn??40);
  if(!Number.isFinite(turnLimit)||turnLimit<10||turnLimit>120)throw new Error('Порог поворота обвода — от 10 до 120°.');
  const issues=[];
  project.bodies.forEach((body,i)=>{
   if(!body.enabled)return;
   for(let k=1;k<body.sections.length-1;k++){
    const m=stationMetric(body,k,C);if(!m)continue;
    if(Number.isFinite(options.focusX)&&(options.focusX<m.x0||options.focusX>m.x1))continue;
    if(m.turn>turnLimit&&m.deviation>.01*m.diameter){
     const s=body.sections[k];issues.push({code:'pressure_station_kink',severity:'warning',domain:'pressure-risk',evidence:'sampled-section-heuristic',title:body.name+': резкий поворот продольного обвода',detail:`Поворот касательной до ${m.turn.toFixed(1)}°; отклонение станции от перехода между соседями ${m.deviation.toFixed(4)} ft. Возможна чувствительность локальной скорости и давления к сетке.`,action:'Осмотри замысел формы. Для случайной неровности доступен ограниченный ремонт с повторной проверкой.',x:s.x,x0:m.x0,x1:m.x1,point:m.point,body:[i],station:k,count:1,metric:m.turn,deviation:m.deviation,threshold:turnLimit,repair:'station-blend',why:'VSP_Solver::CalculateVorticityGradient uses neighbour normals, areas and inverse centre distance; CalculateSurfacePressures derives pressure from velocity.'});
    }
   }
   for(let k=0;k<body.sections.length;k++){
    const s=body.sections[k];if(!s.width||!s.height)continue;
    if(Number.isFinite(options.focusX)&&Math.abs(options.focusX-s.x)>1e-7)continue;
    const r=C.ring(s,96).slice(0,-1);let turn=0,point=r[0];
    for(let j=0;j<r.length;j++){
     const a=sub(r[j],r[(j+r.length-1)%r.length]),b=sub(r[(j+1)%r.length],r[j]);
     if(norm(a)<1e-10||norm(b)<1e-10)continue;
     const theta=angle(a,b);if(theta>turn){turn=theta;point=r[j];}
    }
    if(turn>60)issues.push({code:'pressure_contour_corner',severity:'warning',domain:'pressure-risk',evidence:'sampled-section-heuristic',title:body.name+': острый участок поперечного контура',detail:`На выборке контур поворачивает на ${turn.toFixed(1)}°. Пик давления у намеренной грани может быть особенностью потенциальной модели, а не ошибкой геометрии.`,action:'Сохрани намеренную грань; проверь локальную сеточную сходимость. Автоматическое скругление этой зоны отключено.',x:s.x,x0:s.x,x1:s.x,point,body:[i],station:k,count:1,metric:turn,why:'Surface normals enter the boundary condition and pressure reconstruction; a geometric corner is not automatically a numerical defect.'});
   }
  });
  return issues;
 }
 const api={scan,stationMetric};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.SectionPressure=api;
})(typeof globalThis!=='undefined'?globalThis:this);
