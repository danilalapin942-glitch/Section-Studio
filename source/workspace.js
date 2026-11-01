/* All editable FUSELAGE components; the section display edits a chosen pair. */
(function(root){'use strict';
 const C=root.SectionCore,V=root.VSPImport;
 function allBodies(p){const a=new Map(Object.entries(p.componentPool||{}));for(const b of p.bodies)if(b.sourceId)a.set(b.sourceId,b);return [...a.values()];}
 function sync(p){if(!p.source)return p;p.componentPool={...(p.componentPool||{})};for(const b of p.bodies)if(b.sourceId)p.componentPool[b.sourceId]=C.clone(b);return p;}
 function seed(p){if(!p.source)return p;sync(p);const g=V.parse(p.source.xml);for(const q of g.all){if(q.type!=='Fuselage'||p.componentPool[q.id])continue;try{p.componentPool[q.id]=V.readBody(q,g.all,'gondola',p.source.units);}catch{}}return p;}
 function select(p,ids){if(!p.source||ids.length!==2||!ids[0]||ids[0]===ids[1])throw Error('Выбери два разных редактируемых корпуса.');const q=seed(C.clone(p));q.bodies=ids.map((id,i)=>{if(i===1&&!id)return {...C.demo().bodies[1],enabled:false,name:'Unused_component'};const b=q.componentPool[id];if(!b)throw Error('Этот компонент доступен только для просмотра. Подготовь его сечения через OpenVSP.');return {...C.clone(b),id:i?'gondola':'fuselage',enabled:true};});q.source.selection=[ids[0],ids[1]||null];sync(q);return q;}
 function key(p){return JSON.stringify(allBodies(p).map(b=>[b.sourceId,V.geometryKey(b)]));}
 function rows(p){if(!p.source)return [];const pool=new Map(allBodies(p).map(b=>[b.sourceId,b]));return V.parse(p.source.xml).all.map(g=>({id:g.id,parent:g.parent,name:pool.get(g.id)?.name||g.name,type:g.type,editable:pool.has(g.id),active:p.bodies.findIndex(b=>b.sourceId===g.id)}));}
 const api={seed,sync,select,allBodies,key,rows};root.SectionWorkspace=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
