"""Bidirectional native surface deviation when station counts change.

Shared source XSec IDs supply parameter guesses. Native surface projection
handles caps without inversion of physical X. This is a finite shape sample,
not a material-point displacement or a certified Hausdorff bound.
"""
import json,math,tempfile
from pathlib import Path
from native_audit import run_script,FACTORS

def visible_ids(sections,layout):
 layout=layout if layout and layout.get('verified')else{}
 window=layout.get('sourceRange',{'start':0,'end':len(sections)-1})
 return {s['id']for i,s in enumerate(sections)if window['start']-1e-9<=i<=window['end']+1e-9}

def anchor_map(a,b,la=None,lb=None):
 la=la if la and la.get('verified')else {'frontCaps':0,'backCaps':0};lb=lb if lb and lb.get('verified')else {'frontCaps':0,'backCaps':0}
 ra=la.get('sourceRange',{'start':0,'end':len(a)-1});rb=lb.get('sourceRange',{'start':0,'end':len(b)-1})
 da=max(1e-10,ra['end']-ra['start']+la['frontCaps']+la['backCaps']);db=max(1e-10,rb['end']-rb['start']+lb['frontCaps']+lb['backCaps'])
 pos={s['id']:(i-rb['start']+lb['frontCaps'])/db for i,s in enumerate(b)if rb['start']-1e-9<=i<=rb['end']+1e-9}
 anchors=[((i-ra['start']+la['frontCaps'])/da,pos[s['id']])for i,s in enumerate(a)if s['id']in pos and ra['start']-1e-9<=i<=ra['end']+1e-9]
 if not anchors:return [(0.,0.),(1.,1.)]
 if anchors[0][0]>0:anchors.insert(0,(0.,0.))
 if anchors[-1][0]<1:anchors.append((1.,1.))
 return anchors

def script_for(gids,meta,after,locks,factor,layouts_before=None,layouts_after=None):
 maps=[];sample_blocks=[];layouts_before=layouts_before or {};layouts_after=layouts_after or {}
 for direction,(src,dst,ls,lt)in enumerate([(meta,after,layouts_before,layouts_after),(after,meta,layouts_after,layouts_before)]):
  for k,gid in enumerate(gids):
   anchors=anchor_map(src[gid]['sections'],dst[gid]['sections'],ls.get(gid),lt.get(gid));us=sorted({round(u,14)for u in [i/128 for i in range(129)]+[u for u,v in anchors]});sample_blocks.append('if(direction=='+str(direction)+'&&k=='+str(k)+'){uValues={'+','.join(format(x,'.17g')for x in us)+'};}');xx=','.join(format(x,'.17g')for x,y in anchors);yy=','.join(format(y,'.17g')for x,y in anchors)
   maps.append(f'if(direction=={direction}&&index=={k}){{array<double> x={{{xx}}},y={{{yy}}};for(uint j=1;j<x.length();j++)if(u<=x[j])return y[j-1]+(y[j]-y[j-1])*(u-x[j-1])/(x[j]-x[j-1]);return y[y.length()-1];}}')
 protected=[]
 for k,gid in enumerate(gids):
  for l in locks:
   if l['geomId']==gid:protected.append(f'if(index=={k}&&x>={l["x0"]/factor:.17g}&&x<={l["x1"]/factor:.17g})return true;')
 return '''double mapped(int direction,int index,double u){MAPS return u;}
bool protectedX(int index,double x){PROTECTED return false;}
int main(){
 array<string> gids=GIDS;file measurements;measurements.open("Projection.txt","w");
 for(int direction=0;direction<2;direction++){
  ClearVSPModel();ReadVSPFile(direction==0?"Before.vsp3":"After.vsp3");Update();
  array<vec3d> pts;array<double> uu,ww;array<int> indices,surfs;
  for(uint k=0;k<gids.length();k++){
   int ns=GetTotalNumSurfs(gids[k]);if(ns>16){Print("SECTION_STUDIO_ERROR");return 1;}
   array<double> uValues;SAMPLE_BLOCKS
   for(int s=0;s<ns;s++)for(uint i=0;i<uValues.length();i++)for(int j=0;j<33;j++){
    double u=uValues[i],w=double(j)/32;pts.insertLast(CompPnt01(gids[k],s,u,w));uu.insertLast(u);ww.insertLast(w);indices.insertLast(k);surfs.insertLast(s);
   }
  }
  if(pts.length()>300000){Print("SECTION_STUDIO_ERROR: Projection sample limit.");return 1;}
  ClearVSPModel();ReadVSPFile(direction==0?"After.vsp3":"Before.vsp3");Update();
  for(uint i=0;i<pts.length();i++){
   int k=indices[i];double u=0,w=0,guess=mapped(direction,k,uu[i]);
   double d=ProjPnt01Guess(gids[k],surfs[i],pts[i],guess,ww[i],u,w);
   // Independent projection is used for protected samples when the local guess
   // does not already demonstrate agreement. Never skip a constant-X cap.
   if(d>1e-6||(d>1e-8&&protectedX(k,pts[i].x()))){double u2=0,w2=0,d2=ProjPnt01(gids[k],surfs[i],pts[i],u2,w2);if(d2>=0&&d2<d){d=d2;u=u2;w=w2;}}
   measurements.writeString(gids[k]+" "+direction+" "+formatFloat(pts[i].x(),"",0,15)+" "+formatFloat(d,"",0,15)+" "+formatFloat(u,"",0,15)+" "+formatFloat(w,"",0,15)+"\\n");
  }
 }
 measurements.close();if(GetNumTotalErrors()>0){while(GetNumTotalErrors()>0){ErrorObj e=PopLastError();Print(e.GetErrorString());}Print("SECTION_STUDIO_ERROR");return 1;}
 Print("SECTION_STUDIO_SAVED: Projection.txt");return 0;
}'''.replace('MAPS','\n'.join(maps)).replace('SAMPLE_BLOCKS','\n'.join(sample_blocks)).replace('PROTECTED','\n'.join(protected)).replace('GIDS','{'+','.join(json.dumps(g)for g in gids)+'}')

def project_changed(executable,old,new,units,meta,after,locks,gids,layouts_before=None,layouts_after=None):
 if not gids:return {}
 factor=FACTORS[units]
 with tempfile.TemporaryDirectory(prefix='StudioProjection_')as temp:
  p=Path(temp);(p/'Before.vsp3').write_text(old,encoding='utf-8');(p/'After.vsp3').write_text(new,encoding='utf-8')
  file=run_script(executable,p,script_for(gids,meta,after,locks,factor,layouts_before,layouts_after),'Projection.txt');samples={gid:[]for gid in gids}
  for line in file.read_text(encoding='utf-8').splitlines():
   gid,direction,x,d,u,w=line.split();vals=[float(v)for v in (x,d,u,w)]
   if not all(math.isfinite(v)for v in vals)or vals[1]<0 or not -1e-9<=vals[2]<=1+1e-9 or not -1e-9<=vals[3]<=1+1e-9:raise ValueError('Неполная нативная проекция поверхности.')
   samples[gid].append((int(direction),vals[0]*factor,vals[1]*factor))
 result={}
 for gid,points in samples.items():
  if not points:result[gid]={'complete':False,'reason':'Нативная проекция не вернула точки.'};continue
  distances=[d for direction,x,d in points];rows=[]
  for l in [l for l in locks if l['geomId']==gid]:
   selected=[d for direction,x,d in points if l['x0']-1e-8<=x<=l['x1']+1e-8];maximum=max(selected)if selected else None
   rows.append(l|{'maximumMoveFt':maximum,'sampleCount':len(selected),'skippedSampleCount':0,'passed':maximum is not None and maximum<=l['toleranceFt']})
  result[gid]={'complete':True,'maximumMoveFt':max(distances),'rmsMoveFt':math.sqrt(sum(x*x for x in distances)/len(distances)),'sampleCount':len(points),'skippedSampleCount':0,'correspondence':'bidirectional-native-surface-projection','anchorsUsed':len(visible_ids(meta[gid]['sections'],(layouts_before or{}).get(gid))&visible_ids(after[gid]['sections'],(layouts_after or{}).get(gid))),'directions':2,'locks':rows,'note':'Отклонение формы по двусторонней выборке 129×33 плюс параметры видимых исходных сечений. Это не перемещение материальных точек; нативная проекция и конечная выборка не дают строгой границы между отсчётами.'}
 return result
