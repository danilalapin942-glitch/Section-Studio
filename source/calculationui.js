(function(root){'use strict';
function init(api){
 const $=id=>document.getElementById(id),C=SectionCore;
 let job=null,report=null,reportXml=null,reportPlan=null,demo=false,renderedSource=null,renderedProfile=null;
 const numeric=id=>{const v=$(id).value.trim();return v?Number(v.replace(',','.')):NaN;};
 const format=v=>Number.isFinite(v)?Number(v).toPrecision(7):'—';
 const numbers=id=>{const values=$(id).value.trim().split(/[;\s]+/).filter(Boolean).map(v=>Number(v.replace(',','.')));if(!values.length||values.some(v=>!Number.isFinite(v)))throw new Error('Используй точку или десятичную запятую, разделяй значения знаком ;');return values;};
 function plan(){return {...(api.getProject().calculationProfile||{}),referenceWing:$('calcWing').value==='manual'?null:$('calcWing').value,referenceMode:$('calcWing').value==='manual'?'manual':'wing',manualReferences:$('calcWing').value==='manual'?{areaFt2:Number($('calcArea').value.replace(',','.')),spanFt:Number($('calcSpan').value.replace(',','.')),lengthFt:Number($('calcChord').value.replace(',','.'))}:null,alphas:numbers('calcAlphas'),machs:numbers('calcMachs'),beta:numeric('calcBeta'),momentReferenceFt:['calcX','calcY','calcZ'].map(id=>numeric(id)),bodyRelation:$('calcRelation').value,minimumGapFt:numeric('calcGap'),wakeIterations:numeric('calcWake'),threads:numeric('calcThreads'),solvers:$('calcSolvers').value==='both'?['vspaero','machline']:[$('calcSolvers').value],relativeTolerance:numeric('calcTolerance')/100,formulation:'dirichlet-morino',offsetFt:numeric('calcOffset'),wakeAngleDeg:numeric('calcWakeAngle'),vspaeroModel:$('calcRepresentation').value,momentConvention:$('calcMoments').value,meshMethod:$('calcMesher').value,vspaeroWake:$('calcWakeModel').value,vspaeroForces:$('calcForces').value,singularityOrder:$('calcOrder').value,residualLimit:1e-6,pressureLimit:10};}
 function installPlan(p={}){
  $('calcAlphas').value=(p.alphas||[0,2,4]).join('; ');$('calcMachs').value=(p.machs||[.3]).join('; ');$('calcBeta').value=p.beta??0;
  ['calcX','calcY','calcZ'].forEach((id,i)=>$(id).value=p.momentReferenceFt?.[i]??0);
  $('calcRelation').value=p.bodyRelation||'separate';$('calcGap').value=p.minimumGapFt??.001;
  $('calcWake').value=p.wakeIterations??15;$('calcThreads').value=p.threads??2;$('calcTolerance').value=100*(p.relativeTolerance??.05);
  $('calcSolvers').value=p.solvers?.length===1?p.solvers[0]:'both';$('calcOffset').value=p.offsetFt??1e-5;$('calcWakeAngle').value=p.wakeAngleDeg??150;$('calcRepresentation').value=p.vspaeroModel||'hybrid';$('calcMoments').value=p.momentConvention||'v4.0-area-omitted';$('calcMesher').value=p.meshMethod||'cfd';$('calcWakeModel').value=p.vspaeroWake||'frozen';$('calcForces').value=p.vspaeroForces||'wake';$('calcOrder').value=p.singularityOrder||'lower';if(p.referenceMode==='manual')$('calcWing').value='manual';else if(p.referenceWing)$('calcWing').value=p.referenceWing;for(const [id,key]of [['calcArea','areaFt2'],['calcSpan','spanFt'],['calcChord','lengthFt']])$(id).value=p.manualReferences?.[key]??'';
 }
 function settingsChanged(){
  try{const p=api.getProject();p.calculationProfile=plan();api.commit(p);render();}catch(e){$('calcMessage').textContent=e.message;}
 }
 function refresh(){
  const p=api.getProject(),source=p.source?.xml||'';
  $('calcRun').disabled=!!job||!p.source||!StudioNative.available;
  $('calcCancel').disabled=!job;
  if(source!==renderedSource||JSON.stringify(p.calculationProfile||{})!==renderedProfile){
   renderedSource=source;renderedProfile=JSON.stringify(p.calculationProfile||{});const select=$('calcWing');select.replaceChildren();
   if(source){const doc=new DOMParser().parseFromString(source,'application/xml');for(const g of doc.querySelectorAll('Vehicle > Geom')){
    if(g.querySelector('GeomBase > TypeName')?.textContent!=='Wing')continue;
    const option=document.createElement('option');option.value=g.querySelector('ParmContainer > ID')?.textContent;option.textContent=g.querySelector('ParmContainer > Name')?.textContent||option.value;select.append(option);
   }}
   const manual=document.createElement('option');manual.value='manual';manual.textContent='Опорные величины вручную';select.append(manual);const wing=[...select.options].find(o=>o.textContent.toLowerCase()==='wing');if(wing)select.value=wing.value;
   installPlan(p.calculationProfile||{});
  }
  render();
 }
 function isCurrent(){
  if(!report||!reportXml)return false;
  try{return api.exportVSP(api.getProject())===reportXml&&JSON.stringify(plan())===reportPlan;}catch{return false;}
 }
 function render(){
  const current=isCurrent();
  for(const [id,key] of [['calcGeometry','geometryChecked'],['calcCompleted','solverCompleted'],['calcIterations','iterationConverged'],['calcConvergence','meshConverged']]){
   const e=$(id);e.className='calc-state'+(report?(report[key]?' passed':' failed'):'');
   e.textContent=e.dataset.label+' · '+(report?(report[key]?'пройдено':'не подтверждено'):'ожидается');
  }
  $('calcCurrent').textContent=report?(current?'Результат соответствует текущей модели и показанному плану.':'Результат относится к сохранённой модели/плану. После изменений нужна новая серия.'):'Серия проверит Coarse, Medium и Fine. Допуск сеточной сходимости не означает совпадение с экспериментом.';
  $('calcCurrent').className='calc-note'+(report&&!current?' warning':'');
  $('calcDownload').disabled=!report||report.state==='running';$('calcReport').disabled=!report;
  const ref=report?.references;
  $('calcReference').textContent=ref?`Sref ${format(ref.areaFt2)} ft² · bref ${format(ref.spanFt)} ft · cref ${format(ref.lengthFt)} ft. Центр моментов: ${ref.momentReferenceFt.join('; ')} ft. ${report.openVSPVersion||''}`:'Опорные площадь, размах и САХ берутся из выбранного крыла после Update в OpenVSP. Координаты ниже задают центр моментов, а не определяют центр тяжести по геометрии.';
  $('calcVerdict').textContent=report?(report.passed?'Проверки перечисленных режимов пройдены':report.error||'Серия завершена с непройденными проверками'):'Расчётная серия ещё не выполнена';
  $('calcVerdict').className='calc-note'+(report?(report.passed?' success':' warning'):'');
  const tbody=$('calcRows');tbody.replaceChildren();
  for(const r of report?.cases||[]){
   const tr=document.createElement('tr');for(const v of [r.level,r.solver,r.mach,r.alpha,format(r.coefficients?.CL),format(r.coefficients?.CD),format(r.coefficients?.Cm),r.passed?'пройдено':'проверить']){const td=document.createElement('td');td.textContent=v;tr.append(td);}tbody.append(tr);
  }
  const comparisons=report?.convergence?.cases||[];
  $('calcMeshResult').textContent=comparisons.length?`Сеточная проверка: ${comparisons.filter(c=>c.passed).length} из ${comparisons.length} режимов. Для допуска используется Medium→Fine, переход Coarse→Medium показан в полном отчёте: CL, CD, CY, Cl, Cm, Cn; относительный допуск ${100*report.plan.relativeTolerance}%, абсолютные допуски записаны в отчёте.`:'';
  draw();
 }
 function draw(){
  const canvas=$('calcPlot'),w=canvas.clientWidth||650,h=230,d=devicePixelRatio||1;canvas.width=w*d;canvas.height=h*d;
  const c=canvas.getContext('2d');c.setTransform(d,0,0,d,0,0);c.fillStyle='#f7fafb';c.fillRect(0,0,w,h);
  const rows=(report?.cases||[]).filter(r=>r.level==='Fine'&&r.mach===report.plan.machs[0]);if(!rows.length){c.fillStyle='#647983';c.fillText('CL(α) · появится после расчёта Fine',20,25);return;}
  const xs=rows.map(r=>r.alpha),ys=rows.map(r=>r.coefficients.CL),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(0,...ys),ymax=Math.max(.01,...ys),pad=(ymax-ymin)*.1;
  const x=v=>45+(w-70)*(v-xmin)/(xmax-xmin||1),y=v=>h-35-(h-60)*(v-ymin+pad)/(ymax-ymin+2*pad);
  c.strokeStyle='#c9d8df';c.beginPath();c.moveTo(45,20);c.lineTo(45,h-35);c.lineTo(w-25,h-35);c.stroke();c.fillStyle='#647983';c.fillText('CL · Fine · M='+rows[0].mach,48,15);c.fillText('α, °',w-37,h-12);c.fillText(ymax.toFixed(3),4,32);c.fillText(ymin.toFixed(3),4,h-37);
  for(const [i,solver] of ['vspaero','machline'].entries()){
   const group=rows.filter(r=>r.solver===solver).sort((a,b)=>a.alpha-b.alpha);if(!group.length)continue;c.strokeStyle=c.fillStyle=['#117a91','#b76a22'][i];c.lineWidth=2;c.beginPath();group.forEach((r,j)=>j?c.lineTo(x(r.alpha),y(r.coefficients.CL)):c.moveTo(x(r.alpha),y(r.coefficients.CL)));c.stroke();for(const r of group){c.beginPath();c.arc(x(r.alpha),y(r.coefficients.CL),3,0,Math.PI*2);c.fill();}c.fillText(solver,50+i*100,h-10);
  }
 }
 async function history(){
  if(!StudioNative.available)return;
  try{const r=await StudioNative.calculationList(),s=$('calcHistory');s.replaceChildren();for(const row of r.reports){const o=document.createElement('option');o.value=row.id;o.textContent=`${row.createdAt.slice(0,19).replace('T',' ')} · ${row.state}`;s.append(o);}}catch(e){$('calcMessage').textContent=e.message;}
 }
 async function run(){
  if(job)throw new Error('Расчёт уже выполняется.');
  const p=api.getProject();if(!p.source)throw new Error('Открой VSP3 или проект с исходным VSP3.');
  const xml=api.exportVSP(p),s=plan();report=null;reportXml=xml;reportPlan=JSON.stringify(s);demo=false;
  $('calcMessage').textContent='Постановка в очередь…';const r=await StudioNative.startJob('calculation',{xml,units:p.source.units,plan:s});job=r.jobId;refresh();
  try{
   while(job){const state=await StudioNative.jobStatus(job);$('calcMessage').textContent=state.message;$('calcProgress').value=state.progress||0;
    if(state.state==='done'){report=state.result.report;break;}
    if(['error','cancelled'].includes(state.state)){await history();throw new Error(state.error||state.message);}
    await new Promise(resolve=>setTimeout(resolve,1200));
   }
  }finally{job=null;refresh();await history();}
  return C.clone(report);
 }
 async function loadSaved(){const id=$('calcHistory').value;if(!id)return;const r=await StudioNative.calculationReport(id);report=r.report;reportXml=null;reportPlan=null;demo=false;render();}
 $('calcConnect').onclick=async()=>{try{await StudioNative.configureMachline($('calcMachline').value);$('calcMessage').textContent='MachLine подключён.';}catch(e){$('calcMessage').textContent=e.message;}};
 $('calcRun').onclick=()=>run().catch(e=>{$('calcMessage').textContent=e.message;api.notice(e.message,true);});
 $('calcCancel').onclick=async()=>{if(job)try{await StudioNative.cancelJob(job);}catch(e){$('calcMessage').textContent=e.message;}};
 $('calcHistoryRefresh').onclick=history;$('calcHistoryLoad').onclick=()=>loadSaved().catch(e=>$('calcMessage').textContent=e.message);
 $('calcReport').onclick=()=>{if(report)api.download(JSON.stringify(report,null,2),'Calculation_'+report.id+'.json','application/json');};
 $('calcDownload').onclick=async()=>{try{if(report)await StudioNative.downloadCalculation(report.id,demo);}catch(e){$('calcMessage').textContent=e.message;}};
 $('calcDemo').onclick=async()=>{try{const r=await StudioNative.calculationDemo();const xml=VSPImport.write(r.project),hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(xml))),b=>b.toString(16).padStart(2,'0')).join('');if(hash!==r.report.sourceHash)throw Error('Исходная модель демонстратора не соответствует SHA-256 отчёта.');api.setProject(r.project);renderedSource=null;refresh();report=r.report;reportXml=api.exportVSP(api.getProject());reportPlan=JSON.stringify(plan());demo=true;render();$('calcMessage').textContent='Открыт учебный контрольный стенд из корпусов и сохранённый отчёт; это не MQ-20. Новая серия запускается отдельной кнопкой.';}catch(e){$('calcMessage').textContent=e.message;}};
 for(const id of ['calcWing','calcAlphas','calcMachs','calcBeta','calcX','calcY','calcZ','calcRelation','calcGap','calcWake','calcThreads','calcTolerance','calcSolvers','calcOffset','calcWakeAngle','calcRepresentation','calcMoments','calcMesher','calcWakeModel','calcForces','calcOrder','calcArea','calcSpan','calcChord'])$(id).onchange=settingsChanged;
 if(StudioNative.available)StudioNative.status().then(s=>{$('calcMachline').value=s.machline||'';history();}).catch(()=>{});
 window.addEventListener('resize',draw);refresh();
 return {refresh,run,getReport:()=>report?C.clone({...report,current:isCurrent()}):null,loadSaved,plan};
}
root.SectionCalculationUI={init};
})(globalThis);
