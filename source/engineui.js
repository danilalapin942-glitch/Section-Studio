(function(root){'use strict';
const IO=['None','Inlet','Inlet + Outlet','Outlet'],GEO=['Flowthrough','To Lip','Flowpath','To Face'];
const MODES=['Flowthrough','Flowthrough + Negative','Flowthrough Negative Only','To Lip','To Face','To Face + Negative','To Face Negative Only','Extend'];
function init(api){
 const $=id=>document.getElementById(id),C=SectionCore,V=VSPImport,dialog=$('engineDialog');
 let info=null,baseXml=null,openingXml=null,gid=null,changes=[],generation=0,session=0,pending=null,timer=null,queue=Promise.resolve();
 function nativeCall(data){const request=queue.catch(()=>{}).then(()=>StudioNative.engine(data));queue=request;return request;}
 const labels={GeomIOType:'Engine Geometry',GeomInType:'Inlet Geometry',GeomOutType:'Outlet Geometry',InletModeType:'Inlet Representation',OutletModeType:'Outlet Representation',EngineShowStationsFlag:'Show Stations',RotExtensionFlag:'Rotate Extension',AutoExtensionFlag:'Auto Extension',AutoExtensionSet:'Extension Set',ExtensionDistance:'Extension Distance'};
 const bools=new Set(['EngineShowStationsFlag','RotExtensionFlag','AutoExtensionFlag']);
 function field(name,p){
  const label=document.createElement('label');label.className='engine-field';label.textContent=labels[name]||name.replace(/(Inlet|Outlet)(Face|Lip)(Index|Mode|U)/,'$1 $2 $3');
  let choices=name==='GeomIOType'?IO:name==='GeomInType'||name==='GeomOutType'?GEO:name.endsWith('ModeType')?MODES:name.endsWith('Mode')?['Index','U']:name==='AutoExtensionSet'?info.sets:null;
  let input=document.createElement(choices?'select':'input');input.dataset.parm=name;input.id='engine_'+name;
  if(choices){choices.forEach((text,i)=>{if(i<p.min||i>p.max)return;const o=document.createElement('option');o.value=i;o.textContent=(name==='AutoExtensionSet'?i+' · ':'')+text;input.append(o);});input.value=String(p.value);}
  else if(bools.has(name)){input.type='checkbox';input.checked=!!p.value;}
  else{input.type='number';input.min=p.min;input.max=p.max;input.step=name.endsWith('Index')?'1':'any';input.value=p.value;}
  input.disabled=!info.active.includes(name);
  input.onchange=()=>{const v=bools.has(name)?Number(input.checked):Number(input.value);if(!Number.isFinite(v)){message('Нужно конечное число.');return;}changes.push({name,value:v});generation++;clearTimeout(timer);timer=setTimeout(()=>preview().catch(e=>message(e.message)),250);};
  label.append(input);return label;
 }
 function message(s){$('engineMessage').textContent=s;}
 function render(){
  if(!info)return;const groups={engineGeneral:['GeomIOType','GeomInType','GeomOutType','EngineShowStationsFlag'],engineInlet:['InletModeType','InletLipMode','InletLipIndex','InletLipU','InletFaceMode','InletFaceIndex','InletFaceU'],engineOutlet:['OutletModeType','OutletLipMode','OutletLipIndex','OutletLipU','OutletFaceMode','OutletFaceIndex','OutletFaceU'],engineExtension:['RotExtensionFlag','AutoExtensionFlag','AutoExtensionSet','ExtensionDistance']};
  for(const [id,names]of Object.entries(groups)){const parent=$(id);parent.replaceChildren();for(const k of names)parent.append(field(k,info.parameters[k]));}
  $('engineUnits').textContent=`${info.version} · ${info.sectionCount} исходных сечений · индексы от 0 · Extension Distance в единицах исходного файла (${api.getProject().source.units}).`;
  const nativeMode=info.values.InletModeType;
  $('engineLimit').textContent=[1,2,5,6,7].includes(nativeMode)||[5,6,7].includes(info.values.OutletModeType)?'Настройка поддержана OpenVSP. Отрицательные поверхности и удлинения могут не получить полный допуск автоматических проверок Studio; результат проверяется отдельно.':'Параметры сохраняются в EngineModel VSP3. Нативная геометрия обновляется OpenVSP; это не постановка расхода воздуха или тяги.';
  draw();
 }
 function draw(){
  const canvas=$('engineStations'),w=canvas.clientWidth||800,h=150,d=devicePixelRatio||1;canvas.width=w*d;canvas.height=h*d;const c=canvas.getContext('2d');c.setTransform(d,0,0,d,0,0);c.fillStyle='#f7fafb';c.fillRect(0,0,w,h);if(!info)return;
  const x=u=>30+u*(w-60);c.strokeStyle='#9db5c0';c.beginPath();c.moveTo(x(0),h/2);c.lineTo(x(1),h/2);c.stroke();c.fillStyle='#647983';c.font='11px system-ui';
  for(let i=0;i<info.sectionCount;i++){const u=i/(info.sectionCount-1);c.fillText(String(i),x(u)-3,h/2+25);c.beginPath();c.moveTo(x(u),h/2-4);c.lineTo(x(u),h/2+4);c.stroke();}
  if(info.values.EngineShowStationsFlag)for(const [i,k]of ['InletLip','InletFace','OutletLip','OutletFace'].entries()){
   if(!info.active.includes(k+'Mode'))continue;const u=info.values[k+'Mode']?info.values[k+'U']:info.values[k+'Index']/(info.sectionCount-1);c.strokeStyle=c.fillStyle=['#117a91','#458e65','#b76a22','#9e6599'][i];const yy=20+i*15;c.beginPath();c.moveTo(x(u),yy+3);c.lineTo(x(u),h/2-5);c.stroke();c.fillText(k+' · U='+u.toFixed(4),Math.max(5,Math.min(w-155,x(u)+5)),yy);
  }
  c.fillStyle='#647983';c.fillText('Параметр U исходной поверхности · схема привязок',30,h-10);
 }
 async function preview(){
  clearTimeout(timer);if(pending){await pending;if(changes.length)return preview();return info;}
  if(!changes.length&&info)return info;
  const rev=generation,token=session,patch=C.clone(changes);message('OpenVSP проверяет параметры…');$('engineApply').disabled=true;
  pending=nativeCall({xml:baseXml,geomId:gid,changes:patch});
  try{const r=await pending;if(token!==session||!dialog.open)return null;if(rev===generation){info=r;baseXml=V.withEngineValues(baseXml,gid,r.values);changes=[];render();message('Параметры и доступность полей обновлены OpenVSP.');}return r;}
  finally{pending=null;if(token===session)$('engineApply').disabled=!info||!!changes.length;}
 }
 async function load(){
  session++;generation++;clearTimeout(timer);changes=[];info=null;gid=$('engineBody').value;for(const k of ['engineGeneral','engineInlet','engineOutlet','engineExtension'])$(k).replaceChildren();$('engineBody').disabled=true;openingXml=api.exportVSP(api.getProject());baseXml=openingXml;message('Чтение Engine Model из OpenVSP…');$('engineApply').disabled=true;
  const token=session;
  try{const r=await nativeCall({xml:baseXml,geomId:gid,changes:[]});if(token!==session||!dialog.open)return;info=r;render();message('Изменения сначала проверяются в OpenVSP. Применение — отдельной кнопкой.');}
  catch(e){message(e.message);}finally{if(token===session){$('engineApply').disabled=!info;$('engineBody').disabled=false;}}
 }
 async function open(){
  if(!StudioNative.available)throw Error('Запусти локальную программу и подключи OpenVSP.');const p=api.getProject();if(!p.source)throw Error('Сначала открой VSP3.');
  const s=$('engineBody');s.replaceChildren();for(const g of V.parse(p.source.xml).all.filter(g=>g.type==='Fuselage')){const o=document.createElement('option');o.value=g.id;o.textContent=g.name;s.append(o);}if(!s.options.length)throw Error('В файле нет Fuselage.');s.value=p.bodies[api.active()]?.sourceId||s.value;dialog.showModal();await load();
 }
 async function apply(){
  try{
   await preview();if(!info||changes.length)throw Error('Дождись завершения проверки параметров.');
   const p=api.getProject();if(api.exportVSP(p)!==openingXml)throw Error('Модель изменилась. Открой настройки двигателя заново.');
   if((p.shapeLocks||[]).some(l=>l.geomId===gid))throw Error('На этом корпусе есть защищённые зоны. Сними соответствующую защиту перед изменением Engine Model.');
   const original=V.engineParameters(p.source.xml,gid),working=V.engineParameters(openingXml,gid);
   if(JSON.stringify(original.sectionIds)!==JSON.stringify(working.sectionIds))throw Error('Состав исходных станций изменён. Сохрани VSP3 и открой его заново перед настройкой привязок двигателя. Правки контура не требуют этой операции.');
   const q=C.clone(p);q.source.xml=V.withEngineValues(q.source.xml,gid,info.values);
   const values=Object.fromEntries(Object.keys(info.values).sort().map(k=>[k,info.values[k]]));
   for(const b of [...q.bodies,...Object.values(q.componentPool||{})])if(b.sourceId===gid){b.engineIO=values.GeomIOType;b.engineSettings=C.clone(values);}
   q.engineEditHistory=[...(q.engineEditHistory||[]),{geomId:gid,at:new Date().toISOString(),before:original.values,after:values}].slice(-30);
   V.verifySource(q);if(api.commit(q)){dialog.close();api.notice('Engine Model применён. Геометрические и расчётные проверки нужно выполнить заново.');}
  }catch(e){message(e.message);}
 }
 $('engineOpen').onclick=()=>open().catch(e=>api.notice(e.message,true));$('engineBody').onchange=load;
 $('engineApply').onclick=apply;$('engineCheck').onclick=()=>preview().catch(e=>message(e.message));$('engineClose').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{session++;clearTimeout(timer);});window.addEventListener('resize',()=>{if(dialog.open)draw();});
 return {open,preview,apply,getInfo:()=>info?C.clone(info):null};
}
root.SectionEngineUI={init};
})(globalThis);
