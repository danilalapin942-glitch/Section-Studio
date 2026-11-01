const assert=require('assert/strict'),C=require('../source/core');global.SectionCore=C;const T=require('../source/contour');
const near=(a,b,t=1e-10)=>assert(Math.abs(a-b)<t,`${a} != ${b}`);
const s=()=>C.clone(C.demo().bodies[0].sections[3]);
// Splitting changes representation, not the exact piecewise cubic curve.
let a=s(),original=C.clone(a),i=T.insert(a,.08);assert.equal(i%3,0);assert.equal(a.points.length,original.points.length+6);for(let j=0;j<=1024;j++){const p=C.curve(original.points,j/1024,original.knots),q=C.curve(a.points,j/1024,a.knots);p.forEach((v,k)=>near(v,q[k]));}near(T.bound(original,a),0);assert.deepEqual(C.validateBody({...C.demo().bodies[0],sections:C.demo().bodies[0].sections.map((q,j)=>j===3?a:q)}),[]);
// Removal of an inserted point is an exact inverse; mirror is also removed.
T.remove(a,[i]);assert.equal(a.points.length,original.points.length);near(T.bound(original,a),0);assert.deepEqual(a.points.at(-1),a.points[0]);
// An arbitrary deletion is not silently described as shape preserving.
a=s();i=T.insert(a,.08);C.movePoint(a,i,a.points[i][0]-.05,a.points[i][1]+.03);const before=C.clone(a);T.remove(a,[i]);const bound=T.bound(before,a);assert(bound>0);for(let j=0;j<=1024;j++){const p=C.point3(before,C.curve(before.points,j/1024,before.knots)),q=C.point3(a,C.curve(a.points,j/1024,a.knots));assert(Math.hypot(...p.map((v,k)=>v-q[k]))<=bound+1e-10);}
// Bound includes translations and section rotations, in 3D.
a=s();a.roll=20;a.pitch=15;a.yaw=10;const b=C.clone(a);b.z+=.01;b.y=.02;b.width*=1.02;const limit=T.bound(a,b);for(let j=0;j<=512;j++){const p=C.point3(a,C.curve(a.points,j/512,a.knots)),q=C.point3(b,C.curve(b.points,j/512,b.knots));assert(Math.hypot(...p.map((v,k)=>v-q[k]))<=limit+1e-10);}
// Source dimension nodes and seam cannot be removed in symmetric mode.
a=s();for(const idx of [0,6,a.points.length-1])assert.throws(()=>T.remove(a,[idx]));assert.throws(()=>T.remove(a,[1]));assert.throws(()=>T.insert(a,0));assert.throws(()=>T.insert(a,1));
// Free contours allow independent nodes; multiple selected nodes work.
a=s();a.freeform=true;a.symmetric=false;i=T.insert(a,.08);const k=T.insert(a,.18);T.remove(a,[i,k]);assert.equal(a.points.length,original.points.length);near(T.bound(original,a),0);
// Node limit remains compatible with OpenVSP EditCurve and editor validators.
a=s();while((a.points.length-1)/3<128){const u=T.breaks(a),x=(u[0]+u[1])/2;if(x<1e-8)break;T.insert(a,x);}assert(a.points.length<=385);
const m=T.metrics(original);assert(m.areaFt2>0&&m.perimeterFt>0&&Number.isFinite(m.maxCurvaturePerFt));
console.log('Contour split, mirrored/multiple deletion, inverse recovery, closure, 3D displacement bound and limits passed.');
