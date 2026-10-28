const assert=require('node:assert/strict');
const C=require('../source/core.js'),P=require('../source/pressure.js'),A=require('../source/audit.js'),R=require('../source/repair.js');
const p=C.demo();p.bodies[1].enabled=false;
p.bodies[0].sections=[0,2,5.8,6,6.2,10,12].map((x,k)=>({x,y:0,z:k===3?.24:0,width:2,height:2,shape:'ellipse',points:C.preset('ellipse')}));
const baseline=C.clone(p),report=A.checkGeometry(p),issue=report.issues.find(i=>i.code==='pressure_station_kink'&&i.station===3);
assert(issue);assert.equal(issue.evidence,'sampled-section-heuristic');
const r=R.propose(p,issue,{maxMove:.1});
assert.deepEqual(p,baseline);assert.deepEqual(r.project.bodies[1],p.bodies[1]);
assert(r.metricAfter<r.metricBefore*.95);assert(r.maxMove<=r.budget+1e-10);
assert.deepEqual(r.project.bodies[0].sections.map(s=>s.x),p.bodies[0].sections.map(s=>s.x));
for(const k of [0,1,2,4,5,6])assert.deepEqual(r.project.bodies[0].sections[k],p.bodies[0].sections[k]);
assert.deepEqual(R.newRisks(r.before,r.after),[]);assert.equal(r.nativeVerified,false);
for(const configure of [q=>q.bodies[0].sections[3].repairLocked=true,q=>q.bodies[0].wingFitRegion=[5,9],q=>q.bodies[0].sections[3].pitch=10,q=>q.bodies[0].sections[2].knots=C.knotsOf(q.bodies[0].sections[2]).map((v,k)=>k===1?v+.001:v)]){
 const q=C.clone(p);configure(q);assert.throws(()=>R.propose(q,issue,{maxMove:.1}));
}
assert.throws(()=>R.propose(p,issue,{meta:{protectedStations:[[6],[]]}}));
assert.throws(()=>R.propose(p,{...issue,code:'body_overlap'}));
assert.throws(()=>R.propose(p,issue,{maxMove:1e-8}));
const straight=C.clone(p);straight.bodies[0].sections.forEach(s=>s.z=0);assert(!A.checkGeometry(straight).issues.some(i=>i.code==='pressure_station_kink'));
const corner=C.clone(straight);corner.bodies[0].sections[3].points=C.preset('trapezoid');assert(A.checkGeometry(corner).issues.every(i=>i.code!=='pressure_contour_corner'||!i.repair));
console.log('Pressure indicator, bounded repair and protected-zone checks passed.');
