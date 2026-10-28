/* MachLine d62befad: Q = n.B.n = 1-M^2(n.c)^2. Live facets are a preview. */
(function(root){'use strict';
 const SHA='d62befad9d2d62e30106440e29862ebac7dc362c',D=Math.PI/180;
 const sub=(a,b)=>a.map((v,k)=>v-b[k]),dot=(a,b)=>a.reduce((s,v,k)=>s+v*b[k],0),cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],norm=a=>Math.hypot(...a);
 function settings(raw={}){
  if(!raw||typeof raw!=='object'||Array.isArray(raw))throw new Error('Нужен объект настроек MachLine.');
  for(const k of ['mach','alpha','beta','offset'])if(k in raw&&(typeof raw[k]!=='number'||!Number.isFinite(raw[k])))throw new Error('Некорректное число MachLine: '+k);
  const s={mach:Number(raw.mach??1.5),alpha:Number(raw.alpha??0),beta:Number(raw.beta??0),offset:Number(raw.offset??1e-7),offsetType:raw.offsetType??'direct',formulation:raw.formulation??'dirichlet-morino'};
  if(!Number.isFinite(s.mach)||s.mach<0||s.mach>10)throw new Error('Число Маха должно быть от 0 до 10.');
  if(!Number.isFinite(s.alpha)||Math.abs(s.alpha)>89||!Number.isFinite(s.beta)||Math.abs(s.beta)>89)throw new Error('Углы потока должны быть от −89 до 89°.');
  if(!Number.isFinite(s.offset)||s.offset<=0||s.offset>10)throw new Error('Смещение контрольной точки должно быть больше 0 и не больше 10.');
  if(!['direct','local'].includes(s.offsetType)||!['dirichlet-morino','dirichlet-source-free','neumann-mass-flux','neumann-velocity'].includes(s.formulation))throw new Error('Неизвестная настройка MachLine.');
  // Velocity components are explicitly exported; angles follow OpenVSP X aft, Z up.
  const a=s.alpha*D,b=s.beta*D;s.direction=[Math.cos(a)*Math.cos(b),Math.sin(b),Math.sin(a)*Math.cos(b)];
  return s;
 }
 function surfaceMetric(body,lo,hi,raw={},C=root.SectionCore){
  const s=settings(raw);let maximum=0,minQ=1,point=[lo,0,0],facets=0;
  const xx=[lo,lo+(hi-lo)/4,lo+(hi-lo)/2,lo+3*(hi-lo)/4,hi];
  for(let k=0;k<xx.length-1;k++){
   const a=C.sectionAt(body,xx[k]),b=C.sectionAt(body,xx[k+1]);if(!a||!b)continue;
   const copies=body.mirrorY?[1,-1]:[1];
   for(const sign of copies){const ra=C.ring(a.section,64).map(p=>[p[0],p[1]*sign,p[2]]),rb=C.ring(b.section,64).map(p=>[p[0],p[1]*sign,p[2]]);
    for(let j=0;j<64;j++)for(const tri of [[ra[j],rb[j],rb[j+1]],[ra[j],rb[j+1],ra[j+1]]]){
     const n=cross(sub(tri[1],tri[0]),sub(tri[2],tri[0])),l=norm(n);if(l<1e-14)continue;
     facets++;const t=Math.min(1,Math.abs(dot(n,s.direction)/l)),inclination=Math.asin(t)/D,q=1-s.mach*s.mach*t*t;
     if(inclination>maximum){maximum=inclination;point=tri[0].map((v,d)=>(v+tri[1][d]+tri[2][d])/3);}minQ=Math.min(minQ,q);
    }
   }
  }
  return {inclination:maximum,minQ,point,facets,x0:lo,x1:hi};
 }
 function stationMetric(body,k,raw={},C=root.SectionCore){
  if(k<1||k>=body.sections.length-1)return null;
  const a=surfaceMetric(body,body.sections[k-1].x,body.sections[k].x,raw,C),b=surfaceMetric(body,body.sections[k].x,body.sections[k+1].x,raw,C);
  return {...(a.inclination>=b.inclination?a:b),minQ:Math.min(a.minQ,b.minQ),x0:a.x0,x1:b.x1,facets:a.facets+b.facets};
 }
 function scan(project,options={},C=root.SectionCore){
  if(options.solver!=='machline')return [];
  const s=settings(options.machline),issues=[],mu=s.mach>1?Math.asin(1/s.mach)/D:null;
  const bi=project.bodies.findIndex(b=>b.enabled);if(bi<0)return [];
  const base=project.bodies[bi].sections[0],global={x:base.x,x0:base.x,x1:base.x,point:[base.x,base.y||0,base.z],body:[bi],count:1,domain:'machline-risk',evidence:'source-condition',why:'flow.f90 / panel_calc_g_to_ls_transform @ '+SHA};
  if(s.mach===1){issues.push({...global,code:'machline_sonic',severity:'error',title:'MachLine: M = 1 запрещено решателем',detail:'В flow_init при M = 1 выполняется STOP. Правка геометрии этого не устраняет.',action:'Задай действительный режим расчёта; автоматически менять число Маха нельзя.'});return issues;}
  if(Math.abs(s.mach-1)<.1)issues.push({...global,code:'machline_transonic',severity:'warning',title:'MachLine: близость к звуковому режиму',detail:'Линейная потенциальная модель не описывает трансзвуковые скачки. Порог ±0,1 — предупреждение Studio, а не граница применимости из кода.',action:'Проверь применимость метода к выбранному режиму; ремонт формы не подтверждает физическую точность.'});
  const coordinateScale=Math.max(1,...project.bodies.flatMap(b=>b.sections.flatMap(p=>[Math.abs(p.x),Math.abs(p.y||0),Math.abs(p.z)])));
  if(s.formulation!=='neumann-mass-flux'&&(s.offsetType==='direct'||s.formulation==='neumann-velocity')&&s.offset<32*Number.EPSILON*coordinateScale)issues.push({...global,code:'machline_offset_roundoff',severity:'warning',evidence:'floating-point-heuristic',title:'MachLine: offset близок к точности координат',detail:'Смещение меньше 32·ε·масштаба координат. При сложении точка может остаться на вершине или грани; это эвристика Studio.',action:'Проверь единицы и заданный offset. Его значение автоматически не меняется.'});
  if(s.mach<=1)return issues;
  project.bodies.forEach((body,i)=>{if(!body.enabled)return;
   for(let k=0;k<body.sections.length-1;k++){
    const lo=body.sections[k].x,hi=body.sections[k+1].x;if(Number.isFinite(options.focusX)&&(options.focusX<lo||options.focusX>hi))continue;
    const m=surfaceMetric(body,lo,hi,s,C);if(m.minQ>.05)continue;
    let station=null,deviation=0;
    for(const j of [k,k+1]){const p=root.SectionPressure?.stationMetric(body,j,C);if(p&&p.turn>10&&p.deviation>.005*p.diameter&&p.deviation>deviation){station=j;deviation=p.deviation;}}
    const blocked=m.minQ<=1e-12;
    issues.push({code:blocked?'machline_inclination':'machline_near_characteristic',severity:blocked?'error':'warning',domain:'machline-risk',evidence:'preview-facets',title:body.name+(blocked?': риск недопустимого наклона MachLine':': панель близка к углу Маха'),detail:`На предварительных гранях наклон до ${m.inclination.toFixed(2)}° при угле Маха ${mu.toFixed(2)}°; Q = ${m.minQ.toFixed(5)}. Реальная сетка OpenVSP может иметь другие нормали.`,action:station===null?'Проверь обвод и реальную TRI-сетку. Торцы, кромки и прямые переходы автоматически не перестраиваются.':'Для локальной неровности доступен ограниченный ремонт; после него нужна проверка реальной TRI-сетки.',x:m.point[0],x0:lo,x1:hi,point:m.point,body:[i],count:1,station,metric:m.inclination,minQ:m.minQ,threshold:mu,repair:station===null?null:'machline-station-blend',why:'panel.f90: abs(Q)<1e-12 or Q<0 causes STOP; near threshold 0.05 is a Studio heuristic.'});
   }
  });return issues;
 }
 function inputJSON(value){
  const number=n=>{if(!Number.isFinite(n))throw new Error('В JSON MachLine должно быть конечное число.');let t=String(n);if(/[eE]/.test(t)&&!t.split(/[eE]/)[0].includes('.'))t=t.replace(/[eE]/,'.0e');return t;};
  const encode=(v,depth)=>{const pad='  '.repeat(depth),next='  '.repeat(depth+1);
   if(typeof v==='number')return number(v);if(v===null||typeof v==='string'||typeof v==='boolean')return JSON.stringify(v);
   if(Array.isArray(v))return '['+v.map(x=>encode(x,depth+1)).join(', ')+']';
   return '{\n'+Object.entries(v).map(([k,x])=>next+JSON.stringify(k)+': '+encode(x,depth+1)).join(',\n')+'\n'+pad+'}';
  };return encode(value,0)+'\n';
 }
 const api={SHA,settings,surfaceMetric,stationMetric,scan,inputJSON};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.SectionMach=api;
})(typeof globalThis!=='undefined'?globalThis:this);
