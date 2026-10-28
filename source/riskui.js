(function(root){'use strict';
 function init(api){
  const $=id=>document.getElementById(id),C=root.SectionCore,fmt=n=>Number(n.toFixed(5)).toString();
  let meshReport=null,meshKey='',job=0,busy=false,chosen=null,draft=null,draftKey='',nativeVerification=null,highlight=null,lastKey='',cam={a:-.8,e:.45},drag=null;
  const mode=()=>$('auditSolver').value;
  const solverOptions=()=>{const a=api.auditOptions();return {solver:a.solver,machline:a.machline};};
  const key=()=>{const p=api.getProject();return JSON.stringify(p.bodies)+'|'+(p.source?.xml||'')+'|'+p.source?.units+'|'+$('meshPreset').value+'|'+['auditGap','auditAngle','auditPressure','auditSolver','machNumber','machAlpha','machBeta','machOffset','machOffsetType','machFormulation','machTriUnits'].map(id=>$(id).value).join(',');};
  function refresh(){
   const p=api.getProject(),k=key();
   if(lastKey&&lastKey!==k){job++;draft=null;nativeVerification=null;draftKey='';renderRepair();}
   lastKey=k;
   const stale=meshReport&&meshKey!==k;
   let valid=true;try{const s=solverOptions().machline;$('machFlow').textContent=`Направление скорости в X/Y/Z: [${s.direction.map(v=>v.toFixed(5)).join(', ')}]. X направлен к хвосту, Z вверх; α задаёт подъём скорости по Z, β — по Y. Проверка по MachLine v4.0, commit ${SectionMach.SHA.slice(0,8)}.`;}catch(e){valid=false;$('machFlow').textContent=e.message;}
   const mach=mode()==='machline';$('machSettings').classList.toggle('hidden',!mach);$('meshPreset').parentElement.classList.toggle('hidden',mach);
   $('meshExplanation').textContent=mach?'TRI строится по текущей модели OpenVSP 3.51. Проверены объёмные поверхности всех включённых типов, в том числе верх и низ крыла. Это проверки до решения системы: отсутствие предупреждений не гарантирует корректность давления или сходимость.':'Строится входная сетка VSPAERO после пересечений и обрезок OpenVSP 3.51. Тонкие и объёмные поверхности проверяются отдельно. Давление, отрыв и сходимость решения здесь не рассчитываются.';
   $('meshTitle').textContent=mach?'TRI-сетка и риски MachLine':'Реальная входная сетка VSPAERO';$('meshRun').textContent=mach?'Проверить TRI для MachLine':'Проверить сетку VSPAERO';
   for(const id of ['machTriSave','machInputSave']){$(id).classList.toggle('hidden',!mach);$(id).disabled=!meshReport||stale||meshReport.kind!=='machline-tri-preflight';}
   $('meshRun').disabled=busy||!p.source||!StudioNative.available||!valid;
   $('machTriOpen').disabled=busy||!StudioNative.available||!valid;
   $('machTriUnits').disabled=busy;
   $('meshSave').disabled=!meshReport||stale;
   $('meshPreset').disabled=busy;
   if(!meshReport&&!busy)$('meshSummary').textContent=!p.source?'Открой VSP3 для проверки реальной сетки.':!StudioNative.available?'Запусти Start_Section_Studio.bat и подключи OpenVSP 3.51.':`Нажми «${mach?'Проверить TRI для MachLine':'Проверить сетку VSPAERO'}». Аэродинамический решатель не запускается.`;
   else if(stale&&!busy)$('meshSummary').textContent='Модель или режим изменились. Показан прежний отчёт; повтори проверку сетки.';
   $('meshSummary').classList.toggle('warning',!!stale);
   $('meshStale').classList.toggle('hidden',!stale);
   renderLocks();
  }
  function renderLocks(){
   const p=api.getProject();for(let i=0;i<2;i++){
    const a=C.sectionAt(p.bodies[i],api.cursor()),e=$('repairLock'+i);if(!e)continue;
    e.disabled=!a||a.index<0||!p.bodies[i].enabled;e.checked=!!a?.section.repairLocked;
   }
  }
  for(let i=0;i<2;i++)$('repairLock'+i).onchange=()=>{
   const p=api.getProject(),a=C.sectionAt(p.bodies[i],api.cursor());if(!a||a.index<0)return;
   const q=C.clone(p);q.bodies[i].sections[a.index].repairLocked=$('repairLock'+i).checked;api.commit(q);
  };
  function installReport(r,k){meshReport=r;meshKey=k;highlight=null;renderMesh();refresh();}
  async function run(){
   if(busy)return;const p=api.getProject();if(!p.source)return;
   const k=key(),seq=++job;busy=true;refresh();$('meshSummary').textContent='OpenVSP строит и проверяет входную сетку…';
   try{
    const xml=api.exportVSP(p),result=await StudioNative.audit({xml,units:p.source.units,preset:$('meshPreset').value,...solverOptions()});
    if(seq!==job||k!==key()){$('meshSummary').textContent='Модель изменилась во время проверки. Результат не применён.';return;}
    installReport(result.report,k);api.notice(`Сетка ${mode()==='machline'?'MachLine':'VSPAERO'}: ${result.report.summary.errors} ошибок, ${result.report.summary.warnings} предупреждений. Давление не рассчитывалось.`);
   }catch(e){if(seq===job){$('meshSummary').textContent=e.message;api.notice(e.message,true);}}
   finally{busy=false;refresh();}
  }
  function renderMesh(){
   if(!meshReport)return;const s=meshReport.summary;
   $('meshSummary').textContent=`${meshReport.openVSPVersion} · ${s.nodes} узлов · ${s.panels} панелей · объёмных частей ${s.thickParts}, тонких ${s.thinParts} · ошибок ${s.errors}, предупреждений ${s.warnings}${s.proximityLimited?' · поиск близости ограничен':''}`;
   $('meshCoverage').textContent=`Проверена входная сетка после обрезок. Наборы: thick ${meshReport.thickSet}, thin ${meshReport.thinSet}${meshReport.useMode?' · применён Mode':''}${meshReport.symmetry?' · половина по симметрии':''}. ${meshReport.excludedComponents.length?'Не вошли: '+meshReport.excludedComponents.map(p=>p.name).join(', ')+'.':'Все исходные компоненты вошли в сетку.'} ${s.info?'Отдельно отмечены двигательные или открытые границы: '+s.info+'.':''}`;
   if(meshReport.kind==='machline-tri-preflight'){
    const a=meshReport.settings;$('meshSummary').textContent=`${meshReport.openVSPVersion} → MachLine · ${s.nodes} узлов · ${s.panels} треугольников · M ${a.mach} · сверхнаклонных ${s.superinclinedPanels} · ошибок ${s.errors}, предупреждений ${s.warnings}${s.offsetLimited||s.proximityLimited?' · проверка ограничена':''}`;
    $('meshCoverage').textContent=`Полная объёмная TRI-сетка в ft; верх и низ крыла сохранены. Наборы VSPAERO и его Mode не применяются. ${meshReport.excludedComponents.length?'Не вошли: '+meshReport.excludedComponents.map(p=>p.name).join(', ')+'.':'Все исходные компоненты вошли.'} Критерии официального MachLine ${meshReport.solverCommit.slice(0,8)}; контрольные точки номинальные. ${s.mergedNodes?'Объединено совпадающих узлов: '+s.mergedNodes+'.':''}`;
    if(meshReport.externalMesh)$('meshCoverage').textContent=`Внешний файл ${meshReport.fileName}, единицы ${meshReport.sourceUnits} → ft. Теги не сопоставлены компонентам текущего VSP3; этот отчёт не подтверждает ремонт модели. Критерии MachLine ${meshReport.solverCommit.slice(0,8)}; контрольные точки номинальные.`;
   }
   const list=$('meshIssues');list.replaceChildren();
   for(const issue of meshReport.issues){
    const bt=document.createElement('button');bt.className='audit-issue '+issue.severity;bt.dataset.code=issue.code;
    for(const [tag,text] of [['strong',issue.component+': '+issue.title],['span',`X = ${fmt(issue.x)} ft · панелей в группе ${issue.count}`],['span',issue.detail],['span',issue.action]]){const el=document.createElement(tag);el.textContent=text;bt.append(el);}
    bt.onclick=()=>{highlight=issue;drawMesh();const p=api.getProject(),bi=p.bodies.findIndex(b=>b.sourceId===issue.geomId),candidate=api.getAudit()?.issues.find(i=>i.repair&&i.body.includes(bi)&&issue.x>=i.x0&&issue.x<=i.x1);
     $('meshSelection').textContent=`Выбрано: ${issue.component}, X = ${fmt(issue.x)} ft. ${candidate?'Найдена неровность редактируемого корпуса; открыт предпросмотр ремонта.':'Для этой причины нет безопасного локального ремонта. Проверь геометрию или сетку вручную.'}`;
     if(candidate&&meshKey===key()){api.setCursor(candidate.x);inspect(candidate);}
    };list.append(bt);
   }
   if(!meshReport.issues.length){const el=document.createElement('p');el.className='audit-empty';el.textContent='По этим проверкам дефектов не обнаружено. Распределение давления и сеточную сходимость нужно проверять расчётом.';list.append(el);}
   drawMesh();
  }
  function canvas(id){const el=$(id),w=el.clientWidth||700,h=el.clientHeight||300,d=devicePixelRatio||1;el.width=Math.round(w*d);el.height=Math.round(h*d);const c=el.getContext('2d');c.setTransform(d,0,0,d,0,0);c.clearRect(0,0,w,h);return [c,w,h];}
  function drawMesh(){
   const [c,w,h]=canvas('meshView');if(!meshReport){c.fillStyle='#647983';c.fillText('Реальная расчётная сетка появится после проверки.',18,30);return;}
   const m=meshReport.mesh,limits=[0,1,2].map(d=>m.nodes.reduce((s,p)=>[Math.min(s[0],p[d]),Math.max(s[1],p[d])],[Infinity,-Infinity])),mid=limits.map(r=>(r[0]+r[1])/2);
   const raw=p=>{const x=p[0]-mid[0],y=p[1]-mid[1],z=p[2]-mid[2],a=x*Math.cos(cam.a)+y*Math.sin(cam.a),b=-x*Math.sin(cam.a)+y*Math.cos(cam.a);return [a,z*Math.cos(cam.e)-b*Math.sin(cam.e),b*Math.cos(cam.e)+z*Math.sin(cam.e)];};
   const rp=m.nodes.map(raw),bounds=rp.reduce((s,p)=>[Math.min(s[0],p[0]),Math.max(s[1],p[0]),Math.min(s[2],p[1]),Math.max(s[3],p[1])],[Infinity,-Infinity,Infinity,-Infinity]);
   const scale=Math.min((w-50)/Math.max(1e-6,bounds[1]-bounds[0]),(h-50)/Math.max(1e-6,bounds[3]-bounds[2])),ox=w/2-(bounds[0]+bounds[1])*scale/2,oy=h/2+(bounds[2]+bounds[3])*scale/2;
   const colors=new Map();for(const i of meshReport.issues)for(const f of i.panels)if(i.severity==='error'||!colors.has(f))colors.set(f,i.severity);
   const selection=new Set(highlight?.panels||[]),step=Math.max(1,Math.ceil(m.faces.length/18000));
   const draw=m.faces.flatMap((face,i)=>i%step&&!colors.has(i)?[]:[{i,p:face.map(n=>rp[n]),depth:face.reduce((v,n)=>v+rp[n][2],0)/face.length}]);draw.sort((a,b)=>a.depth-b.depth);
   for(const f of draw){c.beginPath();f.p.forEach((p,j)=>j?c.lineTo(ox+p[0]*scale,oy-p[1]*scale):c.moveTo(ox+p[0]*scale,oy-p[1]*scale));c.closePath();c.fillStyle=selection.has(f.i)?'#9753b4':colors.get(f.i)==='error'?'#da665a':colors.get(f.i)==='warning'?'#dfb74c':'#b5cad1';c.fill();c.strokeStyle='#687f8970';c.lineWidth=.4;c.stroke();}
   c.fillStyle='#647983';c.font='11px system-ui';c.fillText(`Входная сетка · ft · показано ${draw.length} / ${m.faces.length} панелей`,12,18);
   if(highlight){const p=raw(highlight.point);c.beginPath();c.arc(ox+p[0]*scale,oy-p[1]*scale,6,0,Math.PI*2);c.strokeStyle='#8b2ab1';c.lineWidth=3;c.stroke();}
  }
  $('meshView').onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,a:cam.a,v:cam.e};e.currentTarget.setPointerCapture(e.pointerId);};
  $('meshView').onpointermove=e=>{if(!drag)return;cam.a=drag.a+(e.clientX-drag.x)*.008;cam.e=Math.max(-1.3,Math.min(1.3,drag.v+(e.clientY-drag.y)*.008));drawMesh();};
  for(const n of ['pointerup','pointercancel'])$('meshView').addEventListener(n,()=>drag=null);
  $('meshRun').onclick=run;$('meshPreset').onchange=()=>{refresh();drawMesh();};
  $('machTriOpen').onclick=()=>$('machTriFile').click();
  $('machTriUnits').onchange=()=>{refresh();drawMesh();};
  $('machTriFile').onchange=async e=>{
   const file=e.target.files[0];if(!file||busy){e.target.value='';return;}const k=key(),seq=++job;busy=true;refresh();$('meshSummary').textContent='Проверяется внешний TRI…';
   try{if(file.size>40_000_000)throw new Error('Предел ASCII TRI — 40 МБ.');const tri=await file.text();if(seq!==job||k!==key())return;
    const result=await StudioNative.auditTri({tri,fileName:file.name,units:$('machTriUnits').value,machline:solverOptions().machline});if(seq!==job||k!==key())return;installReport(result.report,k);api.notice('Внешний TRI проверен. Связь сетки с текущим VSP3 и готовность аэродинамического расчёта не подтверждаются.');
   }catch(error){if(seq===job){$('meshSummary').textContent=error.message;api.notice(error.message,true);}}
   finally{busy=false;refresh();e.target.value='';}
  };
  $('meshSave').onclick=()=>{if(!meshReport||meshKey!==key())return;const {mesh,panelInclinations,...report}=meshReport;api.download(JSON.stringify({program:'Section Studio 1.0',project:api.getProject().name,report},null,2),api.getProject().name+'_'+mode()+'_mesh_risks.json','application/json');};
  $('machTriSave').onclick=()=>{if(!meshReport||meshKey!==key()||meshReport.kind!=='machline-tri-preflight')return;const m=meshReport.mesh,text=`${m.nodes.length} ${m.faces.length}\n`+m.nodes.map(p=>p.join(' ')).join('\n')+'\n'+m.faces.map(f=>f.map(n=>n+1).join(' ')).join('\n')+'\n'+m.faceParts.join('\n')+'\n';api.download(text,'Mesh.tri','text/plain');api.notice('Mesh.tri сохранена в футах. Предупреждения относятся к этой сетке; экспорт не подтверждает готовность расчёта.');};
  $('machInputSave').onclick=()=>{if(!meshReport||meshKey!==key()||meshReport.kind!=='machline-tri-preflight')return;const s=meshReport.settings;
   const input={flow:{freestream_velocity:s.direction,freestream_mach_number:s.mach},geometry:{file:'Mesh.tri',mirror_about:'none',spanwise_axis:'+y',singularity_order:'lower',reference:{area:1,length:1,CG:[0,0,0]},wake_model:{wake_present:true,wake_shedding_angle:90,trefftz_distance:-1}},solver:{formulation:s.formulation,control_point_offset:s.offset,control_point_offset_type:s.offsetType,matrix_solver:'GMRES',run_checks:true},post_processing:{pressure_rules:{isentropic:s.mach>0,incompressible:s.mach===0}},output:{body_file:'Body.vtk',wake_file:'Wake.vtk',control_point_file:'ControlPoints.vtk',report_file:'Report.json',verbose:true}};
   api.download(SectionMach.inputJSON(input),'MachLine_input_template.json','application/json');api.notice('Скачан шаблон. Задай reference.area в ft², reference.length и CG в ft; сейчас стоят 1, 1 и [0,0,0]. Настрой след под модель и разреши предупреждения перед расчётом.');
  };
  function inspect(issue){chosen=C.clone(issue);draft=null;nativeVerification=null;draftKey='';$('repairTitle').textContent=issue.title;$('repairReason').textContent=issue.detail;$('repairMessage').textContent=SectionRepair.eligibility(api.getProject(),chosen,api.auditMeta())||'Доступно ограниченное сглаживание одной станции. Соседние станции и X сохраняются; зона влияния проверяется отдельно.';renderRepair();$('repairDialog').showModal();}
  $('repairZone').onclick=()=>{
   const report=api.getAudit(),x=api.cursor(),p=api.getProject();const issue=report?.issues.find(i=>i.repair&&i.body.includes(api.active())&&x>=i.x0&&x<=i.x1);
   if(issue)inspect(issue);else api.notice('В текущей зоне нет предупреждения с поддерживаемым ремонтом. Выбери резкий поворот продольного обвода.',true);
  };
  function buildPreview(){
   try{const maxMove=Number($('repairBudget').value.replace(',','.'));draft=SectionRepair.propose(api.getProject(),chosen,{maxMove,options:api.auditOptions(),meta:api.auditMeta()});draftKey=key();nativeVerification=null;renderRepair();}
   catch(e){draft=null;nativeVerification=null;renderRepair();$('repairMessage').textContent=e.message;}
  }
  function renderRepair(){
   const blocked=chosen?SectionRepair.eligibility(api.getProject(),chosen,api.auditMeta()):'Нет выбранной зоны.';
   $('repairPreview').disabled=!!blocked||busy;
   $('repairAuto').disabled=!!blocked||busy||!!(api.getProject().source&&!StudioNative.available);
   $('repairNative').disabled=!draft||busy||!StudioNative.available||!api.getProject().source;
   $('repairApply').disabled=!draft||busy||draftKey!==key()||!!(api.getProject().source&&!nativeVerification?.verified);
   if(blocked&&chosen)$('repairMessage').textContent=blocked;
   if(draft){
    $('repairMessage').textContent=`${draft.metricKind==='inclination'?'Наклон к потоку':'Поворот обвода'}: ${draft.metricBefore.toFixed(2)}° → ${draft.metricAfter.toFixed(2)}°. Смещение управляющих точек до ${fmt(draft.maxMove)} ft; предел ${fmt(draft.budget)} ft (не больше 5% меньшего местного габарита). Новых рисков предварительной формы нет. ${draft.metricAfter>chosen.threshold?'Предупреждение в зоне остаётся: угол выше выбранного порога. ':''}${api.getProject().source?!nativeVerification?'До применения нужна проверка реальной поверхности и сетки.':'':'Учебная форма: проверены только сечения редактора; после экспорта проверь сетку OpenVSP.'}`;
    if(nativeVerification){$('repairMessage').textContent+=nativeVerification.verified?` Локальный ремонт прошёл проверку OpenVSP / ${nativeVerification.solver||'VSPAERO'}: фактическое смещение на выборке ${fmt(nativeVerification.nativeMaxMoveFt)} ft; вне зоны ${fmt(nativeVerification.nativeOutsideMoveFt)} ft.${nativeVerification.inclinationBefore!=null?' Наклон реальной TRI: '+nativeVerification.inclinationBefore.toFixed(2)+'° → '+nativeVerification.inclinationAfter.toFixed(2)+'°.':''} По всей сетке остаётся ошибок: ${nativeVerification.after.summary.errors}, предупреждений: ${nativeVerification.after.summary.warnings}.`:' Ремонт отклонён: '+nativeVerification.reasons.join(' ');}
    drawRepair();
   }else{const [c,w,h]=canvas('repairView');c.fillStyle='#647983';c.fillText('Построй предпросмотр: исходная форма останется в редакторе.',15,30);}
  }
  function drawRepair(){
   if(!draft)return;const [c,w,h]=canvas('repairView'),before=api.getProject().bodies[draft.body].sections[draft.station],after=draft.project.bodies[draft.body].sections[draft.station],a=C.ring(before,160),b=C.ring(after,160),all=a.concat(b),bounds=all.reduce((s,p)=>[Math.min(s[0],p[1]),Math.max(s[1],p[1]),Math.min(s[2],p[2]),Math.max(s[3],p[2])],[Infinity,-Infinity,Infinity,-Infinity]);
   const scale=Math.min((w-55)/(bounds[1]-bounds[0]),(h-55)/(bounds[3]-bounds[2])),ox=w/2-(bounds[0]+bounds[1])*scale/2,oy=h/2+(bounds[2]+bounds[3])*scale/2;
   for(const [r,color,dash] of [[a,'#527a91',[5,3]],[b,'#b66c23',[]]]){c.beginPath();r.forEach((p,j)=>j?c.lineTo(ox+p[1]*scale,oy-p[2]*scale):c.moveTo(ox+p[1]*scale,oy-p[2]*scale));c.strokeStyle=color;c.setLineDash(dash);c.lineWidth=2;c.stroke();}c.setLineDash([]);c.fillStyle='#647983';c.font='12px system-ui';c.fillText(`X = ${fmt(before.x)} ft · синий пунктир — до · оранжевый — после`,12,18);
  }
  async function verify(){
   if(!draft||busy||!api.getProject().source)return;
   const k=draftKey,preview=draft,p=api.getProject(),seq=++job;busy=true;renderRepair();refresh();$('repairMessage').textContent='Проверяются сетки до / после, смещение native-поверхности и защищённые зоны…';
   try{
    const xml=api.exportVSP(p),generated=api.exportVSP(preview.project),id=p.bodies[preview.body].sourceId,a=VSPImport.parse(xml).all.find(g=>g.id===id),b=VSPImport.parse(generated).all.find(g=>g.id===id);
    const candidateXml=xml.slice(0,a.range.start)+generated.slice(b.range.start,b.range.end)+xml.slice(a.range.end);
    const protectedZones=p.bodies[preview.body].wingFitRegion?[p.bodies[preview.body].wingFitRegion]:[];
    const result=await StudioNative.verifyRepair({xml,candidateXml,bodyId:id,units:p.source.units,preset:$('meshPreset').value,budget:preview.budget,zone:preview.zone,protectedZones,code:chosen.code,...solverOptions()});
    if(seq!==job||k!==key()||draft!==preview)return;
    nativeVerification=result;draft.nativeVerified=result.verified;draft.candidateXml=candidateXml;renderRepair();
   }catch(e){if(seq===job){nativeVerification={verified:false,reasons:[e.message]};renderRepair();}}
   finally{busy=false;refresh();renderRepair();}
  }
  function apply(){
   if(!draft||draftKey!==key()||busy||api.getProject().source&&!nativeVerification?.verified)return;
   const q=C.clone(draft.project),r=draft,v=nativeVerification;
   q.repairLog=[...(q.repairLog||[]),{version:'1.0',time:new Date().toISOString(),code:chosen.code,solver:mode(),solverSettings:solverOptions().machline,metricKind:r.metricKind,body:q.bodies[r.body].name,station:r.station,x:q.bodies[r.body].sections[r.station].x,zone:r.zone,budgetFt:r.budget,maxControlMoveFt:r.maxMove,angleBefore:r.metricBefore,angleAfter:r.metricAfter,nativeVerified:!!v?.verified,nativeMaxMoveFt:v?.nativeMaxMoveFt,inclinationBefore:v?.inclinationBefore,inclinationAfter:v?.inclinationAfter,sampling:v?.sampling}].slice(-60);
   if(api.commit(q)){job++;$('repairDialog').close();draft=null;nativeVerification=null;if(v?.verified)installReport(v.after,key());api.notice('Локальный ремонт применён. «Отменить» возвращает исходную форму. Распределение давления проверяется расчётом.');}
  }
  $('repairPreview').onclick=buildPreview;$('repairNative').onclick=verify;$('repairApply').onclick=apply;
  $('repairAuto').onclick=async()=>{buildPreview();if(draft&&api.getProject().source)await verify();};
  $('repairBudget').oninput=()=>{job++;draft=null;nativeVerification=null;renderRepair();};
  $('repairClose').onclick=()=>{$('repairDialog').close();};$('repairDialog').addEventListener('close',()=>{job++;draft=null;nativeVerification=null;});
  window.addEventListener('resize',()=>{drawMesh();if(draft)drawRepair();});
  refresh();drawMesh();
  return {refresh,inspect,run,getReport:()=>meshReport?C.clone({...meshReport,current:meshKey===key()}):null,getRepair:()=>draft?C.clone({...draft,verification:nativeVerification}):null,preview:buildPreview,verify,apply};
 }
 root.SectionRiskUI={init};
})(globalThis);
