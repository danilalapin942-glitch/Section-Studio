const assert=require('node:assert/strict');
const C=require('../source/core'),P=require('../source/pressure'),M=require('../source/machline'),A=require('../source/audit'),R=require('../source/repair');
const p=C.demo();p.bodies[1].enabled=false;
p.bodies[0].sections=[0,2,5.8,6,6.2,10,12].map((x,k)=>({x,y:0,z:k===3?.24:0,width:2,height:2,shape:'ellipse',points:C.preset('ellipse')}));
const options={solver:'machline',machline:{mach:1.5}},original=C.clone(p),report=A.checkGeometry(p,options),issue=report.issues.find(i=>i.code==='machline_inclination'&&i.station===3);
assert(issue);const draft=R.propose(p,issue,{options});assert.equal(draft.metricKind,'inclination');assert(draft.metricAfter<draft.metricBefore*.95);assert(draft.maxMove<=draft.budget);assert.deepEqual(p,original);assert.deepEqual(draft.project.bodies[1],p.bodies[1]);
for(const k of [0,1,2,4,5,6])assert.deepEqual(draft.project.bodies[0].sections[k],p.bodies[0].sections[k]);
for(const change of [q=>q.bodies[0].sections[2].repairLocked=true,q=>q.bodies[0].wingFitRegion=[5,7],q=>q.bodies[0].sections[3].roll=5]){const q=C.clone(p);change(q);assert.throws(()=>R.propose(q,issue,{options}));}
assert.throws(()=>R.propose(p,issue,{options,meta:{protectedStations:[[6],[]]}}));assert.throws(()=>R.propose(p,{...issue,station:0},{options}));
assert(A.checkGeometry(p,{solver:'machline',machline:{mach:1}}).issues.some(i=>i.code==='machline_sonic'));
assert(!A.checkGeometry(p,{solver:'machline',machline:{mach:.5}}).issues.some(i=>i.code==='machline_inclination'));
assert(!R.newRisks({issues:[issue]},{issues:[{...issue,code:'machline_near_characteristic',severity:'warning'}]}).length);
assert(R.newRisks({issues:[{...issue,code:'machline_near_characteristic',severity:'warning'}]},{issues:[issue]}).length);
console.log('MachLine regime, bounded repair, invariant and protection contracts passed.');
const input={offset:1e-7,small:1.234e-16,name:'file1e-7',integer:2};const text=M.inputJSON(input);assert(text.includes('1.0e-7'));assert.deepEqual(JSON.parse(text),input);assert.throws(()=>M.settings({mach:true}));
