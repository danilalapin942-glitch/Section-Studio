"""Native 1.1 assembly checks, preservation measurements and geometry passport.

Only the installed vspscript executable is required. No third-party Python
packages. All native operations run on temporary copies, including CompGeom.
"""
from __future__ import annotations
import hashlib,json,math,re,tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
from native_audit import run_script,FACTORS,canonical
from version import VERSION
from machline_audit import read_tri
from spatial_geometry import check_pairs,triangle_area,distance_field
from geometry_frames import frame_of,section_plane,local
from native_projection import project_changed
from surface_tools import NATIVE_SEMANTICS,read_semantics,smoothness

def value(n,path,default=0.):
    e=n.find(path);return float(e.get('Value'))if e is not None else default

def describe(xml,factor):
    out={}
    for g in ET.fromstring(xml).findall('./Vehicle/Geom'):
        gid=g.findtext('ParmContainer/ID');typ=g.findtext('GeomBase/TypeName');secs=g.findall('FuselageGeom/XSecSurf/XSec');L=value(g,'ParmContainer/Design/Length')
        frame=frame_of(g,factor)
        ss=[{'id':s.findtext('ParmContainer/ID'),'curveType':int(s.findtext('XSec/XSecCurve/XSecCurve/Type','-1')),**section_plane(s,frame)}for s in secs]
        for t in ss:t['x']=t['center'][0]
        out[gid]={'name':g.findtext('ParmContainer/Name'),'type':typ,'frame':frame,'sections':ss,'lengthFt':L*factor if secs else None,'engineIO':int(value(g,'ParmContainer/EngineModel/GeomIOType')),'symmetry':int(value(g,'ParmContainer/Sym/Sym_Planar_Flag')),'orderPolicy':int(value(g,'ParmContainer/Design/OrderPolicy')),'canonical':canonical(g)}
    return out

def native_script(dense=False,areas=False,semantic=False):
    nu=1025 if dense else 33
    return r'''int main(){
 ClearVSPModel();ReadVSPFile("Source.vsp3");Update();
 if(GetVSPVersionMajor()!=3||GetVSPVersionMinor()!=51){Print("SECTION_STUDIO_ERROR: Requires OpenVSP 3.51.x.");return 1;}
 // Read-back verifies the same surface state OpenVSP will actually export.
 WriteVSPFile("Reloaded.vsp3",SET_ALL);ClearVSPModel();ReadVSPFile("Reloaded.vsp3");Update();
 array<string> ids=FindGeoms();int diagnostic=GetNumSets()-1;
 for(uint k=0;k<ids.length();k++){string t=GetGeomTypeName(ids[k]);bool use=t=="Fuselage"||t=="Wing"||t=="Pod"||t=="Stack"||t=="BOR"||t=="Ellipsoid";SetSetFlag(ids[k],diagnostic,use);SetGeomName(ids[k],ids[k]);}
 Update();ExportFile("Assembly.tri",diagnostic,EXPORT_CART3D);
 int totalSurfs=0;for(uint k=0;k<ids.length();k++)totalSurfs+=GetTotalNumSurfs(ids[k]);if(totalSurfs<1)totalSurfs=1;int maxnu=800000/(65*totalSurfs);if(maxnu<2)maxnu=2;
 file samples;samples.open("Samples.txt","w");
 for(uint k=0;k<ids.length();k++){
  string g=ids[k],typ=GetGeomTypeName(g);int ns=GetTotalNumSurfs(g);if(ns<1||ns>16)continue;
  int nu=typ=="Fuselage"?SS_NU:65,nw=65;if(nu>maxnu)nu=maxnu;
  samples.writeString(g+" "+ns+" "+nu+" "+nw+"\n");
  for(int s=0;s<ns;s++)for(int i=0;i<nu;i++)for(int j=0;j<nw;j++){
   vec3d p=CompPnt01(g,s,double(i)/(nu-1),double(j)/(nw-1));
   samples.writeString(formatFloat(p.x(),"",0,15)+" "+formatFloat(p.y(),"",0,15)+" "+formatFloat(p.z(),"",0,15)+"\n");
  }
 }
 samples.close();
 SS_SEMANTICS
 SS_AREAS
 if(GetNumTotalErrors()>0){while(GetNumTotalErrors()>0){ErrorObj e=PopLastError();Print(e.GetErrorString());}Print("SECTION_STUDIO_ERROR");return 1;}
 file info;info.open("AssemblyInfo.txt","w");info.writeString(GetVSPVersion()+"\n");info.close();
 Print("SECTION_STUDIO_SAVED: AssemblyInfo.txt");return 0;
}'''.replace('SS_NU',str(nu)).replace('SS_SEMANTICS',NATIVE_SEMANTICS if semantic else '').replace('SS_AREAS',r'''
 // Cart3D export may leave an auxiliary MeshGeom in memory. Exclude it from
 // CompGeom instead of counting the same aircraft twice.
 array<string> after=FindGeoms();for(uint k=0;k<after.length();k++){bool original=false;for(uint j=0;j<ids.length();j++)if(after[k]==ids[j])original=true;if(!original)SetSetFlag(after[k],diagnostic,false);}
 file wa;wa.open("WetArea.txt","w");string cg=ComputeCompGeom(diagnostic,false,0);string r=FindLatestResultsID("Comp_Geom");
 array<double> areas=GetDoubleResults(r,"Wet_Area");array<string> names=GetStringResults(r,"Comp_Name");
 for(uint i=0;i<areas.length();i++)wa.writeString((i<names.length()?names[i]:formatInt(i))+" "+formatFloat(areas[i],"",0,15)+"\n");wa.close();
'''if areas else '')

def collect(executable,root,xml,units,dense=False,areas=False,semantic=False):
    factor=FACTORS[units];meta=describe(xml,factor);names={k:v['name']for k,v in meta.items()}
    with tempfile.TemporaryDirectory(prefix='StudioAssembly_')as tmp:
        p=Path(tmp);(p/'Source.vsp3').write_text(xml,encoding='utf-8')
        info=run_script(executable,p,native_script(dense,areas,semantic),'AssemblyInfo.txt')
        if(p/'Assembly.tri').stat().st_size>64*1024*1024:raise ValueError('Нативная TRI превышает предел 64 МБ.')
        mesh=read_tri(p/'Assembly.tri',factor,p/'Assembly.tkey',names)
        samples={}
        with(p/'Samples.txt').open(encoding='utf-8')as stream:
            while header:=stream.readline():
                gid,ns,nu,nw=header.split();ns,nu,nw=map(int,(ns,nu,nw))
                if gid not in meta or not 1<=ns<=16 or not 2<=nu<=1025 or nw!=65:raise ValueError('Некорректная нативная выборка.')
                surfs=[]
                for _ in range(ns):
                    rows=[]
                    for i in range(nu):
                        row=[tuple(float(v)*factor for v in stream.readline().split())for j in range(nw)]
                        if any(len(q)!=3 or not all(math.isfinite(v)for v in q)for q in row):raise ValueError('Нефинитная координата OpenVSP.')
                        rows.append(row)
                    surfs.append(rows)
                samples[gid]=surfs
        wet=[]
        if areas:
            for line in(p/'WetArea.txt').read_text(encoding='utf-8').splitlines():
                name,a=line.rsplit(' ',1);wet.append({'geomId':name,'name':names.get(name,name),'areaFt2':float(a)*factor**2})
        return {'version':info.read_text(encoding='utf-8').strip(),'mesh':mesh,'samples':samples,'metadata':meta,'wetArea':wet,'semantics':read_semantics(p,meta,mesh,factor)if semantic else None,'reloaded':(p/'Reloaded.vsp3').read_text(encoding='utf-8')}

def safe_pairs(pairs,ids):
    if not isinstance(pairs,list)or not 1<=len(pairs)<=16:raise ValueError('Задай от 1 до 16 пар компонентов.')
    out=[]
    for p in pairs:
        if not isinstance(p,dict)or p.get('a')not in ids or p.get('b')not in ids or p['a']==p['b']:raise ValueError('Выбери два разных существующих компонента.')
        gap=p.get('minimumGapFt',.001);tol=p.get('toleranceFt',.0001)
        if any(isinstance(x,bool)or not isinstance(x,(float,int))or not math.isfinite(x)or not 0<=x<=10 for x in [gap,tol]):raise ValueError('Зазор и допуск должны быть числами 0…10 ft.')
        out.append({'a':p['a'],'b':p['b'],'minimumGapFt':gap,'toleranceFt':tol})
    return out

def serial_mesh(mesh):
    return {k:mesh[k]for k in ['nodes','faces','faceParts']}|{'parts':list(mesh['parts'].values())}

def passport(bundle,xml,units):
    mesh=bundle['mesh'];meta=bundle['metadata'];parts=mesh['parts'];areas={};bbox={}
    for f,tag in zip(mesh['faces'],mesh['faceParts']):
        gid=parts[tag]['geomId'];t=[mesh['nodes'][n]for n in f];areas[gid]=areas.get(gid,0)+triangle_area(t)
        b=bbox.setdefault(gid,[[math.inf]*3,[-math.inf]*3])
        for p in t:
            for k in range(3):b[0][k]=min(b[0][k],p[k]);b[1][k]=max(b[1][k],p[k])
    root=ET.fromstring(xml);mgr=root.find('.//VSPAEROSettings');mgr=root.find('.//VSPAEROMgr')if mgr is None else mgr;refs={}
    for key in ['Sref','bref','cref']:
        n=next(iter(mgr.iter(key)),None)if mgr is not None else None
        if n is not None:refs[key]=float(n.get('Value'))*FACTORS[units]**(2 if key=='Sref'else 1)
    entries=[]
    for gid,m in meta.items():
        bounds=bbox.get(gid);dimensions={k:bounds[1][i]-bounds[0][i]for i,k in enumerate('xyz')}if bounds else None
        entries.append({k:v for k,v in m.items()if k not in ['canonical','sections']}|{'id':gid,'sectionCount':len(m['sections']),'boundsFt':bounds,'dimensionsFt':dimensions,'grossMeshAreaFt2':areas.get(gid),'hasInternalPaths':m['orderPolicy']==2 and m['engineIO']!=0})
    overall=[[min(b[0][k]for b in bbox.values())for k in range(3)],[max(b[1][k]for b in bbox.values())for k in range(3)]]if bbox else None
    return {'format':'section-studio-geometry-passport','version':VERSION,'units':'ft','areaUnits':'ft2','sourceUnits':units,'sourceHash':hashlib.sha256(xml.encode()).hexdigest(),'boundsFt':overall,'dimensionsFt':{k:overall[1][i]-overall[0][i]for i,k in enumerate('xyz')}if overall else None,'components':entries,'references':refs,'compGeomWetArea':bundle['wetArea'],'grossMeshAreaFt2':sum(areas.values()),'compGeomWetAreaFt2':sum(a['areaFt2']for a in bundle['wetArea']),'physicalExternalWetAreaFt2':None,'surfaceCategories':['external','internal-duct','interface-closure','flow-face-closure'],'areaStatus':'CompGeom учитывает пересечения. Внутренние стенки и условные крышки пока включены в его результат; физическая внешняя площадь требует явного назначения категорий.','solverRun':False}

def assembly(executable,root,data):
    xml=data['xml'];units=data['units'];meta=describe(xml,FACTORS[units]);pairs=[]if data.get('pairs')==[]and data.get('areas')else safe_pairs(data.get('pairs'),meta)
    semantic=bool(data.get('areas')or data.get('semantic'));bundle=collect(executable,root,xml,units,areas=bool(data.get('areas')),semantic=semantic)
    results=check_pairs(bundle['mesh'],pairs,{k:v['name']for k,v in meta.items()})
    refinement=None
    if data.get('refine'):
        tree=ET.fromstring(xml);changed=[]
        for g in tree.findall('./Vehicle/Geom'):
            gid=g.findtext('ParmContainer/ID');near=[q for q in results if gid in (q['a'],q['b'])and q['pointA']is not None]
            if not near:continue
            w=g.find('ParmContainer/Shape/Tess_W')
            if w is not None:w.set('Value',str(min(129,2*int(float(w.get('Value')))-1)));changed.append(gid)
            ss=g.findall('FuselageGeom/XSecSurf/XSec');L=value(g,'ParmContainer/Design/Length')*FACTORS[units];origin=value(g,'ParmContainer/XForm/X_Location')*FACTORS[units]
            for i,s in enumerate(ss):
                if not i:continue
                a=value(ss[i-1],'ParmContainer/XSec/XLocPercent')*L;b=value(s,'ParmContainer/XSec/XLocPercent')*L
                positions=[local(meta[gid]['frame'],q['pointA']if gid==q['a']else q['pointB'])[0]for q in near]
                if any(min(a,b)-.05<=x<=max(a,b)+.05 for x in positions):
                    e=s.find('ParmContainer/XSec/SectTess_U')
                    if e is not None:e.set('Value',str(min(25,2*int(float(e.get('Value')))-1)))
        if changed:
            fine=collect(executable,root,ET.tostring(tree,encoding='unicode'),units,areas=bool(data.get('areas')),semantic=semantic)
            finer=check_pairs(fine['mesh'],pairs,{k:v['name']for k,v in meta.items()})
            refinement={'temporaryOnly':True,'coarsePairs':results,'minimumChangesFt':[abs(a['distanceFt']-b['distanceFt'])if a['distanceFt']is not None and b['distanceFt']is not None else None for a,b in zip(results,finer)],'complete':all(p['complete']for p in results+finer),'note':'Уточнена поперечная сетка выбранных тел и продольные интервалы у минимума. Разность двух сеток — индикатор чувствительности, не строгая граница погрешности CAD.'}
            bundle,results=fine,finer
    r={'format':'section-studio-spatial-gaps','version':VERSION,'sourceHash':hashlib.sha256(xml.encode()).hexdigest(),'openVSPVersion':bundle['version'],'units':'ft','pairs':results,'complete':all(p['complete']for p in results),'passed':all(p['passed']for p in results),'mesh':serial_mesh(bundle['mesh']),'limits':['Глобальный минимум вычислен между треугольниками именно этой сетки. Погрешность аппроксимации аналитических поверхностей отдельно не оценена.','В 3D отмечены точки минимального расстояния каждой пары; это не непрерывная карта всех зазоров.'],'solverRun':False}
    degenerate=[i for i,f in enumerate(bundle['mesh']['faces'])if triangle_area([bundle['mesh']['nodes'][n]for n in f])<=1e-18]
    r['meshQuality']={'degenerateTriangles':len(degenerate),'firstDegenerateFaces':degenerate[:50],'minimumTriangleAreaFt2':min(triangle_area([bundle['mesh']['nodes'][n]for n in f])for f in bundle['mesh']['faces'])}
    if degenerate:r['passed']=False;r['complete']=False
    r['refinement']=refinement
    if refinement and not refinement['complete']:r['passed']=False;r['complete']=False
    if data.get('distanceMap'):r['distanceField']=distance_field(bundle['mesh'],pairs)
    if semantic:
        r['semanticSurface']=bundle['semantics'];r['smoothness']=smoothness(bundle['semantics'],meta,data.get('intendedEdges',[]))
    if data.get('areas'):r['passport']=passport(bundle,xml,units)
    return {'ok':True,'report':r}

def monotone_runs(rows):
    xs=[sum(p[0]for p in row)/len(row)for row in rows];out=[];start=0;direction=0
    for i in range(1,len(rows)):
        d=1 if xs[i]-xs[i-1]>1e-10 else -1 if xs[i]-xs[i-1]<-1e-10 else 0
        if d and direction and d!=direction:
            if i-start>2:out.append(rows[start:i])
            start=i-1
        if d:direction=d
    if len(rows)-start>2:out.append(rows[start:])
    return out

def compare_samples(old,new,locks,same_parameterization=True):
    if len(old)!=len(new):return {'complete':False,'reason':'Изменилось число нативных поверхностей.'}
    measure=[];skipped=[]
    for a,b in zip(old,new):
        if same_parameterization and len(a)==len(b):
            measure.extend((p[0],math.dist(p,q))for row,rr in zip(a,b)for p,q in zip(row,rr))
            continue
        ar,br=monotone_runs(a),monotone_runs(b)
        if len(ar)!=len(br):return {'complete':False,'reason':'Изменилось число ветвей поверхности; соответствие не установлено.'}
        for aa,bb in zip(ar,br):
            for j in range(len(aa[0])):
                ca=sorted((r[j]for r in aa),key=lambda p:p[0]);cb=sorted((r[j]for r in bb),key=lambda p:p[0]);k=0
                for p in ca:
                    if p[0]<cb[0][0]-1e-7 or p[0]>cb[-1][0]+1e-7:
                        skipped.append(p[0]);continue
                    while k<len(cb)-2 and cb[k+1][0]<p[0]:k+=1
                    x,y=cb[k:k+2];dx=y[0]-x[0]
                    if dx<1e-12:
                        skipped.append(p[0]);continue
                    t=max(0.,min(1.,(p[0]-x[0])/dx));q=tuple(x[d]+t*(y[d]-x[d])for d in range(3));measure.append((p[0],math.dist(p,q)))
    if not measure:return {'complete':False,'reason':'Нет сопоставленных точек.'}
    result={'complete':True,'maximumMoveFt':max(d for x,d in measure),'rmsMoveFt':math.sqrt(sum(d*d for x,d in measure)/len(measure)),'sampleCount':len(measure),'skippedSampleCount':len(skipped),'correspondence':'same-native-parameter'if same_parameterization else 'physical-x-interpolation','locks':[]}
    for lock in locks:
        values=[d for x,d in measure if lock['x0']-1e-8<=x<=lock['x1']+1e-8]
        maximum=max(values)if values else None
        missing=sum(lock['x0']-1e-8<=x<=lock['x1']+1e-8 for x in skipped)
        result['locks'].append(lock|{'maximumMoveFt':maximum,'sampleCount':len(values),'skippedSampleCount':missing,'passed':maximum is not None and not missing and maximum<=lock['toleranceFt']})
        if missing:
            result['complete']=False;result['reason']='Часть защищённой зоны не сопоставлена по X после изменения числа станций. Сохранение заблокировано.'
    return result

def compare(executable,root,data):
    old=data['originalXml'];new=data['xml'];units=data['units'];meta=describe(old,FACTORS[units]);after=describe(new,FACTORS[units]);locks=data.get('locks',[])
    if set(meta)!=set(after):raise ValueError('Для сопоставления должен сохраняться состав компонентов.')
    if not isinstance(locks,list)or len(locks)>256:raise ValueError('Допускается до 256 защищённых зон.')
    for l in locks:
        if not isinstance(l,dict)or l.get('geomId')not in meta:raise ValueError('Неизвестный компонент защищённой зоны.')
        if any(not isinstance(l.get(k),(int,float))or isinstance(l.get(k),bool)or not math.isfinite(l[k])for k in ['x0','x1','toleranceFt'])or l['x1']<=l['x0']or not 0<=l['toleranceFt']<=10:raise ValueError('Неверные границы или допуск защищённой зоны.')
    changed=[gid for gid in meta if len(meta[gid]['sections'])!=len(after[gid]['sections'])]
    guard_only=bool(data.get('protectedOnly'));omitted=[gid for gid in changed if guard_only and not any(l['geomId']==gid for l in locks)];changed=[gid for gid in changed if gid not in omitted]
    a=collect(executable,root,old,units,dense=True,semantic=bool(changed));b=collect(executable,root,new,units,dense=True,semantic=bool(changed));records=[]
    projected=project_changed(executable,old,new,units,meta,after,locks,changed,(a.get('semantics')or{}).get('layouts'),(b.get('semantics')or{}).get('layouts'))
    for gid,m in meta.items():
        unchanged=m['canonical']==after[gid]['canonical'];ls=[l for l in locks if l['geomId']==gid]
        if gid not in a['samples']or gid not in b['samples']:r={'complete':False,'reason':'Компонент не имеет поддерживаемой поверхности.'}
        elif gid in omitted:r={'complete':True,'maximumMoveFt':None,'rmsMoveFt':None,'sampleCount':0,'locks':[],'measurementStatus':'not-requested-by-protection-guard'}
        elif gid in projected:r=projected[gid]
        else:r=compare_samples(a['samples'][gid],b['samples'][gid],ls,len(m['sections'])==len(after[gid]['sections']))
        records.append({'id':gid,'name':m['name'],'parametersUnchanged':unchanged,**r})
    preview={gid:[[row[::2]for row in surf[::max(1,(len(surf)-1)//64)]]for surf in surfs]for gid,surfs in a['samples'].items()}
    return {'ok':True,'report':{'format':'section-studio-preservation','version':VERSION,'sourceHash':hashlib.sha256(new.encode()).hexdigest(),'originalHash':hashlib.sha256(old.encode()).hexdigest(),'components':records,'complete':all(r['complete']for r in records),'locksPassed':all(l['passed']for r in records for l in r.get('locks',[])),'limit':'Конечная нативная выборка. При изменении числа станций используются исходные ID для начальных параметров и двусторонняя проекция на поверхности OpenVSP, включая торцы с постоянным X. Измеряется отклонение формы; между отсчётами возможны пропуски.','reopenedInOpenVSP':True,'scope':'protected-and-unchanged-components'if guard_only else'all-components','sourcePreview':{}if guard_only else preview,'solverRun':False}}
