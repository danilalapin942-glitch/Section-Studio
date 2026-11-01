/* Isolated section drafts: one global transaction on Apply. */
(function(root){'use strict';
function init(api){
 const C=SectionCore,T=SectionContour,$=id=>document.getElementById(id),dialog=$('sectionDetailDialog'),canvas=$('detailCanvas');
 let bodyIndex=0,index=0,original=null,draft=null,bodyStamp='',undo=[],redo=[],selection=[],map=null,drag=null,zoom=1,lastErrors=[];
 const copy=C.clone,number=v=>v.trim()?Number(v.trim().replace(',','.')):NaN,fmt=(v,n=6)=>Number.isFinite(v)?Number(v.toFixed(n)).toString():'не определено';
 const symmetric=()=>!draft.freeform||!!draft.symmetric;
 function snapshot(){return {draft:copy(draft),selection:selection.slice()};}
 function remember(){undo.push(snapshot());if(undo.length>100)undo.shift();redo=[];}
 function restore(s){draft=copy(s.draft);selection=s.selection.slice();update();}
 function error(e){$('detailMessage').textContent=e.message||String(e);$('detailMessage').className='detail-message error';}
 function bodyWithDraft(){const b=copy(api.getProject().bodies[bodyIndex]);b.sections[index]=copy(draft);return b;}
 function mutate(fn){const old=snapshot();try{fn();undo.push(old);if(undo.length>100)undo.shift();redo=[];update();}catch(e){draft=old.draft;selection=old.selection;update();error(e);}}
 function available(){return new Set(C.editable(draft));}
 function selectedNode(){return selection.find(i=>i%3===0);}
 function insert(u){mutate(()=>{const k=T.insert(draft,u);selection=[k];});}
 function remove(){if(!selection.length){error('Выбери один или несколько узлов контура.');return;}mutate(()=>{const q=copy(draft);T.remove(q,selection);draft=q;selection=[];});}
 function selectors(){
  const p=api.getProject(),b=$('detailBody');b.replaceChildren();p.bodies.forEach((v,i)=>{const o=document.createElement('option');o.value=i;o.textContent=v.name;o.disabled=!v.enabled;b.append(o);});b.value=bodyIndex;
  const s=$('detailSection');s.replaceChildren();p.bodies[bodyIndex].sections.forEach((v,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`${i+1} · X=${fmt(v.x)} ft`+(v.width?'':' · точка');o.disabled=!v.width||!v.height;s.append(o);});s.value=index;
 }
 function load(b,k){
  const p=api.getProject(),body=p.bodies[b];if(!body?.enabled)throw Error('Выбери включённый корпус.');
  if(!Number.isInteger(k)||!body.sections[k]?.width||!body.sections[k]?.height)throw Error('Выбери сечение с ненулевыми размерами.');
  bodyIndex=b;index=k;bodyStamp=JSON.stringify(body);original=copy(body.sections[k]);draft=copy(original);selection=[];undo=[];redo=[];zoom=1;selectors();update();
 }
 function switchDraft(b,k){
  if(JSON.stringify(draft)!==JSON.stringify(original)&&!confirm('Перейти к другому сечению? Неприменённый черновик будет закрыт.')){selectors();return;}
  try{load(b,k);}catch(e){selectors();error(e);}
 }
 function update(){
  if(!draft)return;
  for(const key of ['width','height','y','z'])$('detail_'+key).value=fmt(draft[key]||0);
  $('detailFree').checked=!!draft.freeform&&!draft.symmetric;
  $('detailSymmetry').textContent=symmetric()?'Связаны зеркальные точки; размерные узлы и начало обхода защищены.':'Свободный контур: доступны обе стороны. Начало обхода и замыкание сохраняются.';
  const sel=$('detailPoints');sel.replaceChildren();const editable=available(),u=C.knotsOf(draft);
  draft.points.slice(0,-1).forEach((p,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`${i%3?'Ручка':'Узел'} ${i} · U=${fmt(u[i],5)} · ${fmt(p[0]*draft.width)}, ${fmt(p[1]*draft.height)} ft`;o.disabled=!editable.has(i);o.selected=selection.includes(i);sel.append(o);});
  selection=selection.filter(i=>editable.has(i));$('detailSelected').textContent=selection.length?`Выбрано: ${selection.join(', ')}`:'Выбери узел или ручку на контуре.';
  const one=selection.length===1?draft.points[selection[0]]:null;
  for(const [id,k,dim]of [['detailPointY',0,'width'],['detailPointZ',1,'height']]){$(id).disabled=!one;$(id).value=one?fmt(one[k]*draft[dim]):'';}
  $('detailUndo').disabled=!undo.length;$('detailRedo').disabled=!redo.length;$('detailDelete').disabled=!selection.length;
  const m=T.metrics(draft),d=T.bound(original,draft);$('detailMetrics').textContent=`${(draft.points.length-1)/3} сегментов · площадь ${fmt(m.areaFt2,5)} ft² · периметр ${fmt(m.perimeterFt,5)} ft\nМакс. выборочная кривизна ${fmt(m.maxCurvaturePerFt,4)} 1/ft · мин. расстояние узлов ${fmt(m.minAnchorDistanceFt,6)} ft\nВерхняя граница смещения кривой: ${fmt(d,7)} ft (${fmt(d*304.8,4)} мм). Это оценка контура, не всей поверхности корпуса.`;
  lastErrors=C.validateBody(bodyWithDraft(),true);$('detailApply').disabled=lastErrors.length>0||!!drag;
  $('detailMessage').textContent=lastErrors.length?lastErrors[0]:m.hotspots.length?'Контур допустим по локальной проверке. Есть участки большой кривизны: осмотри красные отметки.':'Контур допустим по локальной проверке. Сопряжение соседних станций и расчётная сетка проверяются после применения.';
  $('detailMessage').className='detail-message'+(lastErrors.length?' error':m.hotspots.length?' warning':'');
  draw();
 }
 function draw(){
  if(!draft||!dialog.open)return;const rect=canvas.getBoundingClientRect(),w=Math.max(300,rect.width),h=Math.max(260,rect.height),d=devicePixelRatio||1;canvas.width=w*d;canvas.height=h*d;const c=canvas.getContext('2d');c.setTransform(d,0,0,d,0,0);c.fillStyle='#f7fafb';c.fillRect(0,0,w,h);
  const xy=(s,p)=>[p[0]*s.width+(s.y||0),p[1]*s.height+s.z],all=[...original.points.map(p=>xy(original,p)),...draft.points.map(p=>xy(draft,p))];
  const minY=Math.min(...all.map(p=>p[0])),maxY=Math.max(...all.map(p=>p[0])),minZ=Math.min(...all.map(p=>p[1])),maxZ=Math.max(...all.map(p=>p[1])),scale=Math.min((w-100)/Math.max(.1,maxY-minY),(h-90)/Math.max(.1,maxZ-minZ))*zoom;
  map=drag?.map||{scale,ox:w/2-(minY+maxY)/2*scale,oy:h/2+(minZ+maxZ)/2*scale};
  const pixel=p=>[map.ox+p[0]*map.scale,map.oy-p[1]*map.scale];
  c.strokeStyle='#dae5ea';c.lineWidth=1;c.beginPath();c.moveTo(0,map.oy);c.lineTo(w,map.oy);c.moveTo(map.ox,0);c.lineTo(map.ox,h);c.stroke();
  function curve(s,color,width,dashed=false){c.beginPath();const p=s.points.map(p=>pixel(xy(s,p)));c.moveTo(...p[0]);for(let j=1;j<p.length;j+=3)c.bezierCurveTo(...p[j],...p[j+1],...p[j+2]);c.strokeStyle=color;c.lineWidth=width;c.setLineDash(dashed?[5,5]:[]);c.stroke();c.setLineDash([]);}
  curve(original,'#9fadb5',2,true);curve(draft,'#117a91',2.4);
  if($('detailNeighbors').checked){const ss=api.getProject().bodies[bodyIndex].sections;for(const k of [index-1,index+1])if(ss[k]?.width)curve(ss[k],'#c5b8a6',1,true);}
  const editable=available();
  for(let j=0;j<draft.points.length-1;j+=3){const a=pixel(xy(draft,draft.points[j])),b=pixel(xy(draft,draft.points[j+1])),e=pixel(xy(draft,draft.points[j+2])),f=pixel(xy(draft,draft.points[j+3]));c.strokeStyle='#b6cbd3';c.lineWidth=1;c.beginPath();c.moveTo(...a);c.lineTo(...b);c.moveTo(...e);c.lineTo(...f);c.stroke();}
  draft.points.slice(0,-1).forEach((p,i)=>{const q=pixel(xy(draft,p)),chosen=selection.includes(i),r=i%3?3:5;c.beginPath();c.arc(...q,r+(chosen?2:0),0,2*Math.PI);c.fillStyle=chosen?'#b76a22':editable.has(i)?i%3?'#fff':'#117a91':'#bcc8ce';c.fill();c.strokeStyle=chosen?'#b76a22':'#7a9caa';c.lineWidth=1;c.stroke();});
  const m=T.metrics(draft);c.fillStyle='#ce5144';for(const k of m.hotspots.filter((_,i)=>i%5===0)){const p=m.points[k],q=pixel([p[0]+(draft.y||0),p[1]+draft.z]);c.beginPath();c.arc(...q,3,0,2*Math.PI);c.fill();}
  c.fillStyle='#647983';c.font='12px system-ui';c.fillText('Y → · Z ↑ · ft · до поворотов сечения',16,24);c.fillText('Серый пунктир — исходный контур',16,h-17);
 }
 function eventPoint(ev){const r=canvas.getBoundingClientRect();return [ev.clientX-r.left,ev.clientY-r.top];}
 function hitAt(ev){const p=eventPoint(ev);let result=null,best=12;for(const i of available()){const q=draft.points[i],x=map.ox+(q[0]*draft.width+(draft.y||0))*map.scale,y=map.oy-(q[1]*draft.height+draft.z)*map.scale,dist=Math.hypot(p[0]-x,p[1]-y);if(dist<best){best=dist;result=i;}}return result;}
 canvas.addEventListener('pointerdown',ev=>{if(ev.button!==0||!map)return;const hit=hitAt(ev);if(hit===null){selection=[];update();return;}if(ev.ctrlKey||ev.metaKey){selection=selection.includes(hit)?selection.filter(i=>i!==hit):[...selection,hit];update();return;}selection=[hit];remember();drag={index:hit,map:{...map},pointer:ev.pointerId};canvas.setPointerCapture(ev.pointerId);update();});
 canvas.addEventListener('pointermove',ev=>{if(!drag)return;const p=eventPoint(ev),m=drag.map;let y=(p[0]-m.ox)/m.scale-(draft.y||0),z=(m.oy-p[1])/m.scale-draft.z;if($('detailSnap').checked){const step=number($('detailGrid').value);if(step>0){y=Math.round(y/step)*step;z=Math.round(z/step)*step;}}C.movePoint(draft,drag.index,y/draft.width,z/draft.height);update();});
 for(const name of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(name,()=>{if(!drag)return;drag=null;update();});
 canvas.addEventListener('dblclick',ev=>{if(!map)return;const p=eventPoint(ev);let best=Infinity,u=0;for(let k=1;k<1024;k++){const q=C.curve(draft.points,k/1024,draft.knots),x=map.ox+(q[0]*draft.width+(draft.y||0))*map.scale,y=map.oy-(q[1]*draft.height+draft.z)*map.scale,d=Math.hypot(p[0]-x,p[1]-y);if(d<best){best=d;u=k/1024;}}if(best<18)insert(u);});
 canvas.addEventListener('wheel',ev=>{ev.preventDefault();zoom=Math.max(.3,Math.min(12,zoom*(ev.deltaY<0?1.15:1/1.15)));draw();},{passive:false});
 $('detailPoints').onchange=()=>{selection=Array.from($('detailPoints').selectedOptions).map(o=>Number(o.value));update();};
 $('detailAdd').onclick=()=>{const b=T.breaks(draft),i=selection[0],j=i===undefined?0:Math.floor(i/3);insert((b[j]+b[j+1])/2);};
 $('detailDelete').onclick=remove;
 $('detailSmooth').onclick=()=>mutate(()=>{if(selection.length!==1)throw Error('Выбери один узел.');T.smooth(draft,selection[0]);});
 $('detailUndo').onclick=()=>{if(undo.length){redo.push(snapshot());restore(undo.pop());}};
 $('detailRedo').onclick=()=>{if(redo.length){undo.push(snapshot());restore(redo.pop());}};
 $('detailReset').onclick=()=>mutate(()=>{draft=copy(original);selection=[];zoom=1;});
 $('detailFit').onclick=()=>{zoom=1;draw();};$('detailNeighbors').onchange=draw;
 for(const key of ['width','height','y','z'])$('detail_'+key).onchange=()=>{const v=number($('detail_'+key).value);if(!Number.isFinite(v)||(key==='width'||key==='height')&&v<=0){update();error('Нужно конечное число; размеры должны быть больше нуля.');return;}mutate(()=>{draft[key]=v;});};
 for(const [id,k,dim]of [['detailPointY',0,'width'],['detailPointZ',1,'height']])$(id).onchange=()=>{const v=number($(id).value);if(selection.length!==1||!Number.isFinite(v)){update();error('Нужно конечное число и одна выбранная точка.');return;}mutate(()=>{const i=selection[0],p=draft.points[i].slice();p[k]=v/draft[dim];C.movePoint(draft,i,...p);});};
 $('detailFree').onchange=()=>{const enabled=$('detailFree').checked;if(!enabled&&draft.freeform&&!draft.symmetric){$('detailFree').checked=true;error('Для возврата симметрии используй локальную отмену, исходный контур или симметричный шаблон. Программа не усредняет асимметрию автоматически.');return;}mutate(()=>{draft.freeform=true;draft.symmetric=!enabled;});};
 $('detailCheck').onclick=()=>update();
 $('detailBody').onchange=()=>{const b=Number($('detailBody').value),ss=api.getProject().bodies[b].sections;let k=ss.findIndex(s=>s.width&&s.height);switchDraft(b,k);};
 $('detailSection').onchange=()=>switchDraft(bodyIndex,Number($('detailSection').value));
 async function apply(){try{if(drag)throw Error('Заверши перемещение точки.');const p=api.getProject();if(JSON.stringify(p.bodies[bodyIndex])!==bodyStamp)throw Error('Корпус изменился. Закрой черновик и открой сечение заново.');const errors=C.validateBody(bodyWithDraft(),true);if(errors.length)throw Error(errors[0]);if(JSON.stringify(draft)===JSON.stringify(original)){dialog.close();return false;}const q=copy(p);q.bodies[bodyIndex].sections[index]=copy(draft);q.sectionEditHistory=[...(q.sectionEditHistory||[]),{at:new Date().toISOString(),bodyId:q.bodies[bodyIndex].sourceId||bodyIndex,sectionId:draft.sourceId||index,x:draft.x,anchorsBefore:(original.points.length-1)/3,anchorsAfter:(draft.points.length-1)/3,curveDisplacementBoundFt:T.bound(original,draft)}].slice(-100);if(api.commit(q)){dialog.close();api.notice('Сечение применено одним действием. Исходный вариант доступен в общей истории отмены.');return true;}return false;}catch(e){error(e);return false;}}
 function open(b=api.active(),k=null){const p=api.getProject(),body=p.bodies[b];if(!body?.enabled)throw Error('Выбери включённый корпус.');if(k===null)k=body.sections.reduce((best,s,i)=>s.width&&s.height&&(best<0||Math.abs(s.x-api.cursor())<Math.abs(body.sections[best].x-api.cursor()))?i:best,-1);load(b,k);dialog.showModal();draw();}
 $('sectionDetailOpen').onclick=()=>{try{open();}catch(e){api.notice(e.message,true);}};$('detailApply').onclick=apply;$('detailClose').onclick=()=>dialog.close();
 dialog.addEventListener('keydown',ev=>{if(['INPUT','SELECT','TEXTAREA','BUTTON'].includes(ev.target.tagName))return;if(ev.key==='Delete'||ev.key==='Backspace'){ev.preventDefault();remove();}if((ev.ctrlKey||ev.metaKey)&&ev.key.toLowerCase()==='z'){ev.preventDefault();$(ev.shiftKey?'detailRedo':'detailUndo').click();}});
 dialog.addEventListener('close',()=>{drag=null;});window.addEventListener('resize',()=>{if(dialog.open)draw();});
 return {open,apply,insert,remove,getDraft:()=>draft?copy(draft):null,getSelection:()=>selection.slice()};
}
root.SectionDetailUI={init};
})(globalThis);
