/* OpenVSP rigid component transform: Rx Ry Rz around the native pivot. */
(function(root){'use strict';
 const matrix=angles=>{const [x,y,z]=(angles||[0,0,0]).map(v=>v*Math.PI/180),cx=Math.cos(x),sx=Math.sin(x),cy=Math.cos(y),sy=Math.sin(y),cz=Math.cos(z),sz=Math.sin(z);return [[cy*cz,-cy*sz,sy],[cx*sz+sx*sy*cz,cx*cz-sx*sy*sz,-sx*cy],[sx*sz-cx*sy*cz,sx*cz+cx*sy*sz,cx*cy]];};
 const pivot=b=>{const f=b.referenceFrame||{x:0,y:0,z:0,length:0};return [f.x+(f.originFraction||0)*f.length,f.y,f.z];};
 function vector(b,p,inverse=false){const r=matrix(b.rotation);return [0,1,2].map(i=>p.reduce((s,v,j)=>s+v*(inverse?r[j][i]:r[i][j]),0));}
 function point(b,p,inverse=false){const o=pivot(b),v=vector(b,p.map((x,i)=>x-o[i]),inverse);return v.map((x,i)=>x+o[i]);}
 const active=b=>(b.rotation||[]).some(x=>Math.abs(x)>1e-10);
 const api={matrix,pivot,vector,toWorld:(b,p)=>point(b,p),fromWorld:(b,p)=>point(b,p,true),active};root.SectionFrames=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
