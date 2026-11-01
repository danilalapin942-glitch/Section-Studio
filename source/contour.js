/* Piecewise cubic contour operations; U origin and closure are retained. */
(function(root){'use strict';
const C=root.SectionCore,EPS=1e-9;
const breaks=s=>C.knotsOf(s).filter((_,i)=>i%3===0);
const unique=a=>a.sort((a,b)=>a-b).filter((v,i,a)=>!i||Math.abs(v-a[i-1])>EPS);
const symmetric=s=>!s.freeform||!!s.symmetric;
function requireCurve(s){if(!s.width||!s.height)throw Error('Торцевая точка не имеет редактируемого контура.');}
function insert(s,u){
 requireCurve(s);if(!Number.isFinite(u)||u<=EPS||u>=1-EPS)throw Error('Новая точка должна лежать внутри сегмента.');
 let nodes=breaks(s);if(nodes.some(v=>Math.abs(v-u)<EPS))throw Error('В этом месте уже есть узел.');
 nodes.push(u);if(symmetric(s))nodes.push((1.5-u)%1);nodes=unique(nodes);
 if((nodes.length-1)*3+1>385)throw Error('Достигнут предел 128 кубических сегментов.');
 const q=C.refine(s,nodes);s.points=q.points;s.knots=q.knots;s.shape='custom';return C.knotsOf(s).findIndex((v,i)=>i%3===0&&Math.abs(v-u)<EPS);
}
function remove(s,indices){
 requireCurve(s);const original=C.knotsOf(s);let targets=[];
 for(const i of indices){if(!Number.isInteger(i)||i%3||i<=0||i>=s.points.length-1)throw Error('Для удаления выбери узел контура, кроме начала обхода.');const u=original[i];targets.push(u);if(symmetric(s))targets.push((1.5-u)%1);}
 targets=unique(targets);
 if(symmetric(s)&&targets.some(u=>[0,.25,.5,.75,1].some(v=>Math.abs(v-u)<EPS)))throw Error('Размерные узлы симметричного контура сохраняются.');
 if((s.points.length-1)/3-targets.length<(symmetric(s)?4:2))throw Error('Для замкнутого контура осталось слишком мало сегментов.');
 for(const t of targets.sort((a,b)=>b-a)){
  const u=C.knotsOf(s),p=s.points,i=u.findIndex((v,i)=>i%3===0&&Math.abs(v-t)<EPS);if(i<=0||i>=p.length-1)throw Error('Не найден внутренний узел.');
  const a=i-3,b=i+3,lo=u[a],hi=u[b],span=hi-lo,left=t-lo,right=hi-t;
  const q=[p[a].slice(),p[a].map((v,k)=>v+(p[a+1][k]-v)*span/left),p[b].map((v,k)=>v+(p[b-1][k]-v)*span/right),p[b].slice()];
  s.points=[...p.slice(0,a),...q,...p.slice(b+1)];s.knots=[...u.slice(0,a),lo,lo+span/3,lo+2*span/3,hi,...u.slice(b+1)];
 }
 s.points[s.points.length-1]=s.points[0].slice();s.shape='custom';return s;
}
function bound(before,after){
 // Cubic Bernstein coefficients form a convex combination. Align both curves
 // exactly by subdivision, then bound their physical difference by the largest
 // difference of corresponding control points, including center translation.
 const nodes=unique([...breaks(before),...breaks(after)]),a=C.refine(before,nodes),b=C.refine(after,nodes);
 return Math.max(...a.points.map((p,i)=>{const x=C.point3(before,p),y=C.point3(after,b.points[i]);return Math.hypot(...x.map((v,k)=>v-y[k]));}));
}
function smooth(s,i){
 requireCurve(s);if(i%3||i<=0||i>=s.points.length-1)throw Error('Выбери внутренний узел.');
 const p=s.points,point=p[i],t=[(p[i+3][0]-p[i-3][0])*s.width,(p[i+3][1]-p[i-3][1])*s.height],len=Math.hypot(...t);if(len<1e-12)throw Error('Не определено направление касательной.');
 for(const j of [i-1,i+1]){const l=Math.hypot((p[j][0]-point[0])*s.width,(p[j][1]-point[1])*s.height),sign=j<i?-1:1;C.movePoint(s,j,point[0]+sign*t[0]/len*l/s.width,point[1]+sign*t[1]/len*l/s.height);}
 return s;
}
function metrics(s){
 const pts=Array.from({length:257},(_,i)=>{const p=C.curve(s.points,i/256,s.knots);return [p[0]*s.width,p[1]*s.height];});
 let area=0,perimeter=0,maxCurvature=0,minStep=Infinity;const hotspots=[];
 for(let i=0;i<256;i++){const a=pts[i],b=pts[i+1];area+=a[0]*b[1]-a[1]*b[0];perimeter+=Math.hypot(a[0]-b[0],a[1]-b[1]);}
 for(let i=1;i<256;i++){const a=pts[i-1],b=pts[i],c=pts[i+1],ab=Math.hypot(a[0]-b[0],a[1]-b[1]),bc=Math.hypot(b[0]-c[0],b[1]-c[1]),ac=Math.hypot(a[0]-c[0],a[1]-c[1]),den=ab*bc*ac;const k=den?2*Math.abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))/den:Infinity;if(k>maxCurvature)maxCurvature=k;if(k>20/Math.max(s.width,s.height,1e-9))hotspots.push(i);}
 for(let i=3;i<s.points.length;i+=3){const a=s.points[i-3],b=s.points[i];minStep=Math.min(minStep,Math.hypot((a[0]-b[0])*s.width,(a[1]-b[1])*s.height));}
 return {areaFt2:Math.abs(area)/2,perimeterFt:perimeter,maxCurvaturePerFt:maxCurvature,minAnchorDistanceFt:minStep,hotspots,points:pts,limit:'Sampled metrics and curvature indicator; not pressure or native surface validation.'};
}
const api={insert,remove,bound,smooth,metrics,breaks};root.SectionContour=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
