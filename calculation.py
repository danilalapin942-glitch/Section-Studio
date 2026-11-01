"""Reproducible, local VSPAERO/MachLine calculations. Standard library only.

Geometry, process completion, iteration convergence and mesh convergence are
separate gates. None is an experimental validation of aerodynamic accuracy.
"""
from __future__ import annotations

from collections import defaultdict
import csv
import io
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile

from assembly_audit import assembly
from local_storage import atomic_bytes
from machline_audit import read_tri, inspect_machline, input_json, weld
from mesh_audit import read_vspgeom, inspect_mesh
from native_audit import FACTORS, metadata
from native_control import check_cancel
from version import VERSION

LEVELS = {'Coarse': (17, 5), 'Medium': (25, 7), 'Fine': (33, 9)}
ID = re.compile(r'[a-f0-9]{24}')


def file_digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()


def digest(value):
    if isinstance(value, str):
        value = value.encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def finite(value, label, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError('Некорректный параметр расчёта: ' + label)
    return float(value)


def normalize_plan(raw, xml):
    if not isinstance(raw, dict):
        raise ValueError('Нужны настройки расчётной серии.')
    root = ET.fromstring(xml)
    wings = {g.findtext('ParmContainer/ID'): g for g in root.findall('./Vehicle/Geom') if g.findtext('GeomBase/TypeName') == 'Wing'}
    wing = raw.get('referenceWing')
    if not wing:
        wing = next((k for k, g in wings.items() if g.findtext('ParmContainer/Name', '').lower() == 'wing'), None)
    manual=raw.get('manualReferences') if raw.get('referenceMode')=='manual' else None
    if manual is not None:
        if not isinstance(manual,dict):raise ValueError('Нужны явные опорные величины.')
        manual={k:finite(manual.get(k),k,1e-8,1e12) for k in ('areaFt2','spanFt','lengthFt')}
        wing=None
    if wing not in wings and manual is None:
        raise ValueError('Выбери опорное крыло модели.')
    alphas = raw.get('alphas', [0., 2., 4.])
    machs = raw.get('machs', [.3])
    if not isinstance(alphas, list) or not 2 <= len(alphas) <= 6 or not isinstance(machs, list) or not 1 <= len(machs) <= 3:
        raise ValueError('Нужны 2…6 разных углов атаки и 1…3 числа Маха.')
    alphas = sorted(set(finite(v, 'alpha', -20, 20) for v in alphas))
    machs = sorted(set(finite(v, 'Mach', 0, 3) for v in machs))
    if len(alphas) < 2 or len(alphas)*len(machs) > 12:
        raise ValueError('Нужны разные углы; предел — 12 режимов на одну сетку.')
    if any(.85 <= m <= 1.2 for m in machs):
        raise ValueError('Трансзвуковой диапазон 0,85…1,2 не входит в этот расчётный тракт.')
    solvers = raw.get('solvers', ['vspaero', 'machline'])
    if not isinstance(solvers, list) or not solvers or len(set(solvers)) != len(solvers) or any(s not in ('vspaero', 'machline') for s in solvers):
        raise ValueError('Выбери VSPAERO и/или MachLine.')
    point = raw.get('momentReferenceFt', [0., 0., 0.])
    if not isinstance(point, list) or len(point) != 3:
        raise ValueError('Нужны три координаты центра моментов, ft.')
    point = [finite(v, 'центр моментов', -1e6, 1e6) for v in point]
    relation = raw.get('bodyRelation', 'separate')
    if relation not in ('separate', 'joined'):
        raise ValueError('Неизвестный тип соединения корпусов.')
    plan = dict(referenceWing=wing,referenceMode='manual' if manual else 'wing',manualReferences=manual, alphas=alphas, machs=machs,
                beta=finite(raw.get('beta', 0.), 'beta', -15, 15),
                solvers=solvers, momentReferenceFt=point, bodyRelation=relation,
                minimumGapFt=finite(raw.get('minimumGapFt', .001), 'зазор', 0, 1),
                relativeTolerance=finite(raw.get('relativeTolerance', .05), 'относительный допуск', .001, .2),
                wakeIterations=int(finite(raw.get('wakeIterations', 15), 'итерации следа', 5, 100)),
                threads=int(finite(raw.get('threads', 2), 'число потоков', 1, 8)),
                formulation=raw.get('formulation', 'dirichlet-morino'),
                offsetFt=finite(raw.get('offsetFt', 1e-5), 'offset', 1e-12, .01),
                wakeAngleDeg=finite(raw.get('wakeAngleDeg',150.), 'угол отделения следа', 90, 175),
                vspaeroModel=raw.get('vspaeroModel','hybrid'),
                momentConvention=raw.get('momentConvention','v4.0-area-omitted'),
                meshMethod=raw.get('meshMethod','cfd'),
                vspaeroWake=raw.get('vspaeroWake','frozen'),
                vspaeroForces=raw.get('vspaeroForces','wake'),
                singularityOrder=raw.get('singularityOrder','lower'),
                caseTimeoutSeconds=int(finite(raw.get('caseTimeoutSeconds',300),'время одного режима',30,1800)),
                matrixLimitMiB=finite(raw.get('matrixLimitMiB',4096),'бюджет матрицы, MiB',128,32768),
                residualLimit=finite(raw.get('residualLimit', 1e-6), 'невязка MachLine', 1e-12, 1e-3),
                pressureLimit=finite(raw.get('pressureLimit', 10.), 'предел |Cp| для осмотра', 2, 1000),
                levels=list(LEVELS), engineTreatment='unpowered-native-boundaries')
    if plan['formulation'] not in ('dirichlet-morino', 'dirichlet-source-free'):
        raise ValueError('Для подтверждаемой серии поддержаны две Dirichlet-постановки MachLine.')
    if plan['vspaeroModel'] not in ('hybrid','thick') or plan['momentConvention'] not in ('v4.0-area-omitted','standard'):
        raise ValueError('Неизвестное представление VSPAERO или соглашение о моментах MachLine.')
    if plan['meshMethod'] not in ('cfd','cart3d'):
        raise ValueError('Неизвестный метод триангуляции MachLine.')
    if plan['vspaeroWake'] not in ('frozen','relaxed') or plan['vspaeroForces'] not in ('surface','wake') or plan['singularityOrder'] not in ('lower','higher'):
        raise ValueError('Неизвестная модель следа, интегрирования сил или порядок MachLine.')
    # No user-supplied shell arguments, filenames, executable paths or mesh counts.
    return plan


def refined_xml(xml, level):
    root = ET.fromstring(xml)
    w, u = LEVELS[level]
    for g in root.findall('./Vehicle/Geom'):
        if g.findtext('GeomBase/TypeName') not in ('Wing', 'Fuselage', 'Pod', 'Stack', 'BOR', 'Ellipsoid'):
            continue
        for e in g.findall('ParmContainer/Shape/Tess_W'):
            e.set('Value', str(w))
        for e in g.findall('ParmContainer/Shape/Tess_U'):
            e.set('Value', str(u))
        for e in g.iter('SectTess_U'):
            e.set('Value', str(u))
    return ET.tostring(root, encoding='unicode')


def execute(args, folder, log_name, timeout=900, threads=2):
    """Kill the complete solver process tree on cancellation/timeout."""
    check_cancel()
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS=str(threads), OPENBLAS_NUM_THREADS=str(threads),GFORTRAN_UNBUFFERED_ALL='1')
    options = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)} if os.name == 'nt' else {'start_new_session': True}
    start = time.monotonic()
    with (folder/log_name).open('wb') as log:
        p = subprocess.Popen([str(x) for x in args], cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT, **options)
        try:
            while p.poll() is None:
                check_cancel()
                if time.monotonic()-start > timeout:
                    raise TimeoutError('Расчёт превысил ' + str(timeout) + ' секунд. См. журнал.')
                time.sleep(.1)
        except BaseException:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            else:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            p.wait(timeout=5)
            raise
    check_cancel()
    return {'returncode': p.returncode, 'seconds': time.monotonic()-start, 'log': log_name}


def tail(path, size=5000):
    with path.open('rb') as f:
        f.seek(max(0, path.stat().st_size-size))
        return f.read(size).decode('utf-8', errors='replace')


def prepare_script(plan, factor, level='Coarse'):
    """OpenVSP writes its own v7 setup; StopBeforeRun prevents a flow solve."""
    point = [x/factor for x in plan['momentReferenceFt']]
    script = '''int main(){
ClearVSPModel(); ReadVSPFile("Model.vsp3"); SetVSP3FileName("Model.vsp3"); Update();
if(GetVSPVersionMajor()!=3||GetVSPVersionMinor()!=51){Print("PIPELINE_ERROR: Requires OpenVSP 3.51.x");return 1;}
string wing=REF_WING;
double area=GetParmVal(wing,"TotalArea","WingGeom"),span=GetParmVal(wing,"TotalSpan","WingGeom"),chord=GetParmVal(wing,"MAC","WingGeom");
file refs;refs.open("References.txt","w");refs.writeString(GetVSPVersion()+"\\n"+formatFloat(area,"",0,15)+"\\n"+formatFloat(span,"",0,15)+"\\n"+formatFloat(chord,"",0,15)+"\\n");refs.close();
int thick=GetNumSets()-2,thin=GetNumSets()-1;array<string> ids=FindGeoms();
for(uint k=0;k<ids.length();k++){string kind=GetGeomTypeName(ids[k]);bool w=kind=="Wing";SetSetFlag(ids[k],thin,w);SetSetFlag(ids[k],thick,kind=="Fuselage"||kind=="Pod"||kind=="Stack"||kind=="BOR"||kind=="Ellipsoid");}
string a="VSPAEROComputeGeometry";SetAnalysisInputDefaults(a);array<int> t={thick},n={thin},zero={0},one={1},cpu={THREADS},wake={WAKE};
SetIntAnalysisInput(a,"GeomSet",t);SetIntAnalysisInput(a,"ThinGeomSet",n);SetIntAnalysisInput(a,"UseModeFlag",zero);SetIntAnalysisInput(a,"Symmetry",zero);ExecAnalysis(a);
a="VSPAEROSweep";SetAnalysisInputDefaults(a);SetIntAnalysisInput(a,"GeomSet",t);SetIntAnalysisInput(a,"ThinGeomSet",n);SetIntAnalysisInput(a,"UseModeFlag",zero);SetIntAnalysisInput(a,"Symmetry",zero);SetIntAnalysisInput(a,"RefFlag",zero);
SetIntAnalysisInput(a,"AlphaNpts",one);SetIntAnalysisInput(a,"BetaNpts",one);SetIntAnalysisInput(a,"MachNpts",one);SetIntAnalysisInput(a,"NCPU",cpu);SetIntAnalysisInput(a,"WakeNumIter",wake);SetIntAnalysisInput(a,"StopBeforeRun",one);
array<double> sa={area},sb={span},sc={chord},x={PX},y={PY},z={PZ};SetDoubleAnalysisInput(a,"Sref",sa);SetDoubleAnalysisInput(a,"bref",sb);SetDoubleAnalysisInput(a,"cref",sc);SetDoubleAnalysisInput(a,"Xcg",x);SetDoubleAnalysisInput(a,"Ycg",y);SetDoubleAnalysisInput(a,"Zcg",z);ExecAnalysis(a);
ClearVSPModel();ReadVSPFile("Model.vsp3");Update();ids=FindGeoms();int all=GetNumSets()-1;
for(uint k=0;k<ids.length();k++){string kind=GetGeomTypeName(ids[k]);bool yes=kind=="Wing"||kind=="Fuselage"||kind=="Pod"||kind=="Stack"||kind=="BOR"||kind=="Ellipsoid";SetSetFlag(ids[k],all,yes);if(yes)SetGeomName(ids[k],ids[k]);}
ExportFile("MachMesh.tri",all,EXPORT_CART3D);
if(GetNumTotalErrors()>0){while(GetNumTotalErrors()>0){ErrorObj e=PopLastError();Print(e.GetErrorString());}Print("PIPELINE_ERROR");return 1;}
Print("PIPELINE_PREPARED");return 0;}
'''.replace('REF_WING', json.dumps(plan['referenceWing'])).replace('THREADS', str(plan['threads'])).replace('WAKE', str(plan['wakeIterations'])).replace('PX', repr(point[0])).replace('PY', repr(point[1])).replace('PZ', repr(point[2]))
    if plan.get('manualReferences'):
        ref=plan['manualReferences']
        script=script.replace('string wing=null;','string wing="";')
        script=script.replace('double area=GetParmVal(wing,"TotalArea","WingGeom"),span=GetParmVal(wing,"TotalSpan","WingGeom"),chord=GetParmVal(wing,"MAC","WingGeom");',
            'double area='+repr(ref['areaFt2']/factor**2)+',span='+repr(ref['spanFt']/factor)+',chord='+repr(ref['lengthFt']/factor)+';')
    if plan['vspaeroModel']=='thick':
        script=script.replace('SetSetFlag(ids[k],thin,w);','SetSetFlag(ids[k],thin,false);').replace('SetSetFlag(ids[k],thick,kind=="Fuselage"','SetSetFlag(ids[k],thick,kind=="Wing"||kind=="Fuselage"')
    if plan['vspaeroWake']=='frozen':
        script=script.replace('SetIntAnalysisInput(a,"StopBeforeRun",one);','SetIntAnalysisInput(a,"StopBeforeRun",one);SetIntAnalysisInput(a,"FreezeWakeAtIteration",zero);')
    if plan['meshMethod']=='cfd' and 'machline' in plan['solvers']:
        i=list(LEVELS).index(level)
        mesh='''DeleteAllCFDSources();
double meshLength=chord<span?chord:span;SetCFDMeshVal(CFD_MAX_EDGE_LEN,meshLength*HFACTOR);SetCFDMeshVal(CFD_MIN_EDGE_LEN,meshLength*HFACTOR/6.0);SetCFDMeshVal(CFD_MAX_GAP,meshLength*HFACTOR/24.0);
SetCFDMeshVal(CFD_NUM_CIRCLE_SEGS,CIRCLES);SetCFDMeshVal(CFD_GROWTH_RATIO,1.3);SetCFDMeshVal(CFD_FAR_FIELD_FLAG,0);SetCFDMeshVal(CFD_HALF_MESH_FLAG,0);
SetComputationFileName(CFD_TRI_TYPE,"MachMesh.tri");SetComputationFileName(CFD_TKEY_TYPE,"Cfd.tkey");ComputeCFDMesh(all,SET_NONE,CFD_TRI_TYPE|CFD_TKEY_TYPE);
'''.replace('HFACTOR',str([.3,.2,.16][i])).replace('CIRCLES',str([16,24,32][i]))
        script=script.replace('ExportFile("MachMesh.tri",all,EXPORT_CART3D);',mesh)
    return script


def topology(mesh):
    """Exact welded-edge checks; no global self-intersection proof."""
    welded, _ = weld(mesh)
    nodes, faces = welded['nodes'], welded['faces']
    edges = defaultdict(list)
    adjacency = defaultdict(set)
    for i, f in enumerate(faces):
        for j, a in enumerate(f):
            b = f[(j+1)%3]
            edges[tuple(sorted((a, b)))].append((i, a < b))
    boundary = sum(len(v) == 1 for v in edges.values())
    nonmanifold = sum(len(v) > 2 for v in edges.values())
    winding = sum(len(v) == 2 and v[0][1] == v[1][1] for v in edges.values())
    for v in edges.values():
        for a, _ in v:
            adjacency[a].update(b for b, _ in v if b != a)
    seen, volumes, groups = set(), [], []
    for seed in range(len(faces)):
        if seed in seen:
            continue
        stack, volume, tags = [seed], 0., set()
        seen.add(seed)
        while stack:
            i = stack.pop()
            if welded.get('faceParts'):tags.add(welded['faceParts'][i])
            a,b,c = [nodes[k] for k in faces[i]]
            volume += (a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
            for j in adjacency[i]-seen:
                seen.add(j);stack.append(j)
        volumes.append(volume)
        groups.append(sorted({mesh.get('parts',{}).get(t,{}).get('geomId',str(t)) for t in tags}))
    return dict(boundaryEdges=boundary, nonmanifoldEdges=nonmanifold, inconsistentEdges=winding,
                componentVolumesFt3=volumes,componentGeometryIds=groups, closed=not boundary and not nonmanifold,
                outward=bool(volumes) and all(v > 1e-12 for v in volumes),
                limit='Welded edge connectivity and signed component volume; not a global triangle intersection proof.')


def tri_text(mesh):
    return str(len(mesh['nodes']))+' '+str(len(mesh['faces']))+'\n'+'\n'.join(' '.join(format(v, '.16g') for v in p) for p in mesh['nodes'])+'\n'+'\n'.join(' '.join(str(v+1) for v in f) for f in mesh['faces'])+'\n'+'\n'.join(map(str, mesh['faceParts']))+'\n'


def table_rows(path, header_start):
    if not path.is_file() or path.stat().st_size > 64*1024*1024:
        raise ValueError('Отсутствует или слишком велик результат ' + path.name)
    rows, headers = [], None
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line=re.sub(r'\b(L2|Max)\s+Residual\b',r'\1Residual',line)
        fields = line.split()
        if fields and fields[0] == header_start:
            headers = fields
            continue
        if headers and len(fields) >= len(headers):
            try:
                values = [float(v.replace('D','E')) for v in fields[:len(headers)]]
            except ValueError:
                continue
            rows.append(dict(zip(headers, values)))
    if not rows:
        raise ValueError('Не найдены численные результаты ' + path.name)
    return rows


def parse_vspaero(folder, process, mach, alpha, beta, method='surface'):
    rows = table_rows(folder/'Model.polar', 'Beta')
    history = table_rows(folder/'Model.history', 'Iter')
    if len(rows) != 1:
        raise ValueError('Ожидался один режим VSPAERO.')
    row = rows[0]
    for key, target in [('Mach', mach), ('AoA', alpha), ('Beta', beta)]:
        if not math.isfinite(row.get(key, math.inf)) or abs(row.get(key, math.inf)-target) > 1e-7:
            raise ValueError('Режим в результате VSPAERO не совпадает с запросом.')
    coeff = {k:row[v] for k,v in {'CL':'CLi','CD':'CDi','CY':'CSi','Cl':'CMix','Cm':'CMiy','Cn':'CMiz'}.items()}
    if method=='wake':
        coeff.update(CL=row['CLiw'],CD=row['CDiw'],CY=row['CSiw'])
    if not all(math.isfinite(v) for v in coeff.values()):
        raise ValueError('Неконечные первичные коэффициенты VSPAERO.')
    # VSPAERO history column names contain spaces in log10 residual labels;
    # parse the documented compact file labels instead (see sample fixture).
    last = history[-1]
    residual_keys = [k for k in last if 'Residual' in k or k in ('L2Res','MaxRes')]
    residual = {k:last[k] if math.isfinite(last[k]) else str(last[k]) for k in residual_keys}
    stable = len(history) >= 3 and all(abs(history[-1][k]-history[-2][k]) <= max(.005 if k=='CLtot' else .0005, .01*abs(history[-1][k])) for k in ('CLtot','CDtot'))
    residual_drop=history[0].get('L2Residual',-math.inf)-last.get('L2Residual',math.inf)
    stable=stable and residual_drop>=2 and last.get('L2Residual',math.inf)<=-2
    return dict(solver='vspaero', mach=mach, alpha=alpha, beta=beta, coefficients=coeff,
                additional={k:(row.get(v) if row.get(v) is not None and math.isfinite(row[v]) else None) for k,v in {'CLsurfaceInviscid':'CLi','CDsurfaceInviscid':'CDi','CDtotal':'CDtot','CDviscous':'CDo','CLwake':'CLwtot','CDwake':'CDwtot'}.items()},
                iterations=len(history), residual=residual, log10ResidualDrop=residual_drop if math.isfinite(residual_drop) else None, iterationConverged=stable,
                processCompleted=process['returncode']==0, process=process,
                forceModel=('inviscid wake integration (CLiw/CDiw/CSiw)' if method=='wake' else 'inviscid surface integration (CLi/CDi/CSi)')+'; moments use surface loads; viscous estimate retained separately')


def parse_machline(folder, process, mach, alpha, beta, plan, reference=None):
    p = folder/'Report.json'
    if not p.is_file() or p.stat().st_size > 4*1024*1024:
        raise ValueError('MachLine не создал Report.json.')
    raw = json.loads(p.read_text(encoding='utf-8'))
    solver = raw['solver_results']
    status = solver['solver_status_code']
    if status != 0:
        raise ValueError('MachLine не решил систему: solver_status_code='+str(status)+'. '+tail(folder/'solver.log',1000))
    residual = float(solver['residual']['norm'])
    f = raw['total_forces'];m=raw['total_moments']
    a,b=math.radians(alpha),math.radians(beta)
    cx,cy,cz = [float(f[k]) for k in ('Cx','Cy','Cz')]
    # Pinned MachLine v4.0 divides C_M by l_ref, but omits S_ref in
    # calc_moments. Preserve raw moments and normalize in this adapter.
    area=float(raw['input']['geometry']['reference']['area']) if plan['momentConvention']=='v4.0-area-omitted' else 1.
    native_length=float(raw['input']['geometry']['reference'].get('length',1.))
    span=(reference or plan.get('manualReferences') or {}).get('spanFt',native_length)
    roll_yaw_factor=native_length/span
    coeff = dict(CL=-math.sin(a)*cx+math.cos(a)*cz,
                 CD=math.cos(a)*math.cos(b)*cx+math.sin(b)*cy+math.sin(a)*math.cos(b)*cz,
                 CY=-math.cos(a)*math.sin(b)*cx+math.cos(b)*cy-math.sin(a)*math.sin(b)*cz,
                 Cl=float(m['CMx'])/area*roll_yaw_factor,Cm=float(m['CMy'])/area,Cn=float(m['CMz'])/area*roll_yaw_factor)
    if not all(math.isfinite(v) for v in [residual,*coeff.values()]):
        raise ValueError('MachLine вернул NaN/Inf.')
    if not (folder/'Body.vtk').is_file() or not (folder/'ControlPoints.vtk').is_file():
        raise ValueError('Отсутствуют поля давления или контрольные точки MachLine.')
    pressure = raw.get('pressure_calculations', {})
    extrema = [abs(float(v)) for d in pressure.values() for k,v in d.items() if k in ('min','max')]
    if any(not math.isfinite(v) for v in extrema):
        raise ValueError('MachLine вернул NaN/Inf в поле давления.')
    pressure_ok = bool(extrema) and all(v <= plan['pressureLimit'] for v in extrema)
    return dict(solver='machline',mach=mach,alpha=alpha,beta=beta,coefficients=coeff,
                bodyCoefficients=f,rawMoments=m,momentAdapter=plan['momentConvention'],momentNormalization={'nativeLengthFt':native_length,'rollYawReferenceFt':span,'rollYawFactor':roll_yaw_factor},iterations=solver.get('iterations'),residual={'norm':residual},
                iterationConverged=status==0 and residual<=plan['residualLimit'],
                pressureReviewPassed=pressure_ok,pressureFinite=bool(extrema) and all(math.isfinite(v) for v in extrema),pressure=pressure,solverStatusCode=status,
                processCompleted=process['returncode']==0 and status==0,process=process,
                forceModel='isentropic pressure' if mach else 'incompressible pressure')


def convergence(cases, plan):
    groups = defaultdict(dict)
    for c in cases:
        groups[(c['solver'],c['mach'],c['alpha'],c['beta'])][c['level']] = c
    comparisons=[]
    absolute={'CL':.005,'CD':.0005,'CY':.005,'Cl':.005,'Cm':.005,'Cn':.005}
    for key, rows in groups.items():
        if set(rows) != set(LEVELS):
            comparisons.append({'case':list(key),'passed':False,'reason':'Нет всех трёх сеток.'});continue
        differences=[]
        for lo,hi in [('Coarse','Medium'),('Medium','Fine')]:
            metrics={}
            for k,atol in absolute.items():
                a,b=rows[lo]['coefficients'][k],rows[hi]['coefficients'][k]
                limit=max(atol,plan['relativeTolerance']*abs(b))
                metrics[k]={'difference':abs(a-b),'limit':limit,'passed':abs(a-b)<=limit}
            differences.append({'from':lo,'to':hi,'metrics':metrics,'passed':all(m['passed'] for m in metrics.values())})
        comparisons.append({'case':list(key),'comparisons':differences,'passed':differences[-1]['passed']})
    expected=len(plan['solvers'])*len(plan['machs'])*len(plan['alphas'])
    return {'passed':len(comparisons)==expected and all(x['passed'] for x in comparisons),
            'relativeTolerance':plan['relativeTolerance'],'absoluteTolerances':absolute,'cases':comparisons,
            'limit':'Both mesh intervals reported. Admission uses Medium→Fine; Coarse→Medium shows the trend. Discretization sensitivity, not experimental accuracy.'}


def solver_path(value):
    path=Path(str(value).strip().strip('"')).expanduser()
    if not path.is_file() or path.name.lower() not in ('machline.exe','machline','vspaero','vspaero.exe'):
        raise ValueError('Выбери исполняемый файл MachLine или VSPAERO.')
    if os.name!='nt' and not os.access(path,os.X_OK):
        raise ValueError('Файл решателя не имеет разрешения на запуск.')
    return str(path.resolve())


def discover_machline(root):
    candidates=[]
    if os.environ.get('MACHLINE_EXE'):candidates.append(Path(os.environ['MACHLINE_EXE']))
    for base in [Path(root),*list(Path(root).parents)[:3]]:
        for rel in ('engines/MachLine','runtime/MachLine','MachLine','bin',''):
            for name in ('machline.exe','MachLine.exe','machline','MachLine'):
                candidates.append(base/rel/name)
    for name in ('MachLine','machline','machline.exe'):
        p=shutil.which(name)
        if p:candidates.append(Path(p))
    return next((str(p.resolve()) for p in candidates if p.is_file()),None)


def run_pipeline(vspscript, machline, package_root, store_root, data, progress=lambda *a,**k:None):
    xml,units=data['xml'],data['units']
    plan=normalize_plan(data.get('plan'),xml)
    vspaero=Path(vspscript).parent/('vspaero.exe' if os.name=='nt' else 'vspaero')
    if 'vspaero' in plan['solvers']:solver_path(vspaero)
    if 'machline' in plan['solvers']:
        if not machline:raise ValueError('Подключи MachLine во вкладке расчётов.')
        machline=solver_path(machline)
    ident=secrets.token_hex(12);folder=Path(store_root)/ident;folder.mkdir(parents=True)
    factor=FACTORS[units]
    report={'format':'section-studio-calculation','version':VERSION,'id':ident,
            'createdAt':datetime.now(timezone.utc).isoformat(),'sourceHash':digest(xml),'sourceUnits':units,
            'plan':plan,'planHash':digest(json.dumps(plan,sort_keys=True)),
            'geometryChecked':False,'solverCompleted':False,'iterationConverged':False,'meshConverged':False,
            'passed':False,'state':'running','levels':{},'cases':[],
            'propulsion':'Unpowered geometry with explicitly retained native engine boundaries; no engine mass-flow/jet model.',
            'scope':'Selected modes and meshes only. No experimental accuracy or unrestricted operating-envelope certification.',
            'pressureScope':'MachLine pressure extrema only; no VSPAERO Cp-field admission in this pipeline.',
            'executables':{k:{'filename':Path(v).name,'sha256':file_digest(v),'bytes':Path(v).stat().st_size} for k,v in [('OpenVSP',vspscript),('VSPAERO',vspaero),('MachLine',machline)] if v and (k!='VSPAERO' or 'vspaero' in plan['solvers']) and (k!='MachLine' or 'machline' in plan['solvers'])}}
    def save():
        atomic_bytes(folder/'report.json',(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
    (folder/'Source.vsp3').write_text(xml,encoding='utf-8');save()
    try:
        meta=metadata(xml)
        source_root=ET.fromstring(xml)
        bodies=[g.findtext('ParmContainer/ID') for g in source_root.findall('./Vehicle/Geom') if g.findtext('GeomBase/TypeName')=='Fuselage']
        if plan['bodyRelation']=='separate' and len(bodies)>=2:
            progress('Проверка исходного зазора корпусов',.02)
            ar=assembly(vspscript,package_root,{'xml':xml,'units':units,'semantic':True,'refine':True,
                 'pairs':[{'a':bodies[0],'b':bodies[1],'minimumGapFt':plan['minimumGapFt'],'toleranceFt':.0001}]})['report']
            report['assembly']={k:ar[k] for k in ('sourceHash','complete','passed','pairs','meshQuality')}
            report['assembly']['sourceCorrespondenceComplete']=ar['semanticSurface']['complete']
            # Source-rib correspondence protects edits; this read-only flow path
            # validates the actual solver mesh independently. For engines keep
            # the stricter correspondence gate, since boundary roles matter.
            has_engine=any(metadata(xml)['engine'].values())
            if not ar['complete'] or not ar['passed'] or (has_engine and not ar['semanticSurface']['complete']):
                raise ValueError('Не пройдена нативная проверка исходных корпусов. См. отчёт серии.')
        total=3*len(plan['solvers'])*len(plan['machs'])*len(plan['alphas']);done=0
        for level in LEVELS:
            check_cancel();progress('Подготовка '+level,.05+.9*done/total)
            stage=folder/level;stage.mkdir();model=refined_xml(xml,level)
            (stage/'Model.vsp3').write_text(model,encoding='utf-8')
            (stage/'Prepare.vspscript').write_text(prepare_script(plan,factor,level),encoding='utf-8')
            proc=execute([vspscript,'-script','Prepare.vspscript'],stage,'prepare.log',180,plan['threads'])
            if proc['returncode'] or 'PIPELINE_PREPARED' not in tail(stage/'prepare.log') or 'PIPELINE_ERROR' in tail(stage/'prepare.log'):
                raise ValueError('OpenVSP не подготовил '+level+': '+tail(stage/'prepare.log',2000))
            refs=(stage/'References.txt').read_text(encoding='utf-8').splitlines()
            ref={'areaFt2':float(refs[1])*factor**2,'spanFt':float(refs[2])*factor,'lengthFt':float(refs[3])*factor,
                 'momentReferenceFt':plan['momentReferenceFt'],'wingId':plan['referenceWing'],'method':'explicit manual reference quantities' if plan.get('manualReferences') else 'native TotalArea / TotalSpan / MAC'}
            if not all(math.isfinite(ref[k]) and ref[k]>0 for k in ('areaFt2','spanFt','lengthFt')):
                raise ValueError('Некорректные опорные величины OpenVSP.')
            if report.get('references') and any(abs(report['references'][k]-ref[k])>1e-6 for k in ('areaFt2','spanFt','lengthFt')):
                raise ValueError('Опорные величины изменились между уровнями сетки.')
            report['references']=ref;report['openVSPVersion']=refs[0]
            record={'tessellation':dict(zip(('W','U'),LEVELS[level])),'preflight':{}}
            report['levels'][level]=record
            mach_mesh=None
            if 'vspaero' in plan['solvers']:
                mesh=read_vspgeom(stage/'Model.vspgeom',stage/'Model.vkey',factor)
                audit=inspect_mesh(mesh,metadata(model));record['preflight']['vspaero']=audit
                if audit['summary']['errors'] or audit['summary'].get('proximityLimited'):
                    raise ValueError(level+': расчётная сетка VSPAERO не прошла проверку.')
            if 'machline' in plan['solvers']:
                key=stage/('Cfd.tkey' if plan['meshMethod']=='cfd' else 'MachMesh.tkey')
                mach_mesh=read_tri(stage/'MachMesh.tri',factor,key if key.is_file() else None,meta['components'])
                top=topology(mach_mesh);record['machlineTopology']=top
                if not top['closed'] or not top['outward'] or top['inconsistentEdges']:
                    raise ValueError(level+': TRI не является согласованной замкнутой внешней оболочкой. Открытый сверхзвуковой выход требует отдельного профиля и не допускается этим шаблоном.')
                if plan['bodyRelation']=='joined' and len(bodies)>=2 and not any(set(bodies[:2]).issubset(ids) for ids in top['componentGeometryIds']):
                    raise ValueError(level+': выбран режим общей оболочки, но две исходные поверхности не соединены в расчётной сетке.')
                estimate=24*len(mach_mesh['nodes'])**2/(1024**2)
                record['estimatedDenseMatrixMiB']=estimate
                if estimate>plan['matrixLimitMiB']:
                    raise ValueError(level+': оценка памяти матрицы '+str(round(estimate))+' MiB превышает заданный бюджет. Измени сетку или бюджет на подходящем компьютере.')
                (stage/'Mesh.tri').write_text(tri_text(mach_mesh),encoding='utf-8')
            record['geometryPassed']=True;save()
            for solver in plan['solvers']:
                for mach in plan['machs']:
                    for alpha in plan['alphas']:
                        check_cancel();case_id=solver+'_'+format(mach,'.6g')+'_'+format(alpha,'.6g')
                        case_folder=stage/case_id;case_folder.mkdir()
                        progress(level+' · '+solver+' · M='+str(mach)+' · α='+str(alpha),.05+.9*done/total)
                        if solver=='vspaero':
                            for p in stage.glob('Model.*'):
                                if p.suffix not in ('.vsp3','.vspaero'):shutil.copyfile(p,case_folder/p.name)
                            setup=(stage/'Model.vspaero').read_text(encoding='utf-8')
                            for k,v in {'Mach':mach,'AoA':alpha,'Beta':plan['beta']}.items():
                                setup,n=re.subn(r'^'+k+r'\s*=.*$',k+' = '+repr(v),setup,flags=re.M)
                                if n!=1:raise ValueError('Не найден параметр '+k+' в setup VSPAERO.')
                            (case_folder/'Model.vspaero').write_text(setup,encoding='utf-8')
                            proc=execute([vspaero,'-omp',str(plan['threads']),'Model'],case_folder,'solver.log',plan['caseTimeoutSeconds'],plan['threads'])
                            case=parse_vspaero(case_folder,proc,mach,alpha,plan['beta'],plan['vspaeroForces'])
                        else:
                            audit=inspect_machline(mach_mesh,dict(mach=mach,alpha=alpha,beta=plan['beta'],offset=plan['offsetFt'],offsetType='direct',formulation=plan['formulation']),metadata(model))
                            if audit['summary']['errors'] or audit['summary'].get('proximityLimited') or audit['summary'].get('offsetLimited'):
                                record['preflight']['machline']=audit;save()
                                raise ValueError(level+': MachLine не допускает геометрию в данном режиме.')
                            record['preflight'].setdefault('machline',audit)
                            shutil.copyfile(stage/'Mesh.tri',case_folder/'Mesh.tri')
                            a,b=math.radians(alpha),math.radians(plan['beta'])
                            config={'flow':{'freestream_velocity':[math.cos(a)*math.cos(b),math.sin(b),math.sin(a)*math.cos(b)],'freestream_mach_number':mach},
                              'geometry':{'file':'Mesh.tri','mirror_about':'none','spanwise_axis':'+y','singularity_order':plan['singularityOrder'],'reference':{'area':ref['areaFt2'],'length':ref['lengthFt'],'CG':ref['momentReferenceFt']},'wake_model':{'wake_present':True,'wake_shedding_angle':plan['wakeAngleDeg'],'N_panels':4}},
                              'solver':{'formulation':plan['formulation'],'control_point_offset':plan['offsetFt'],'control_point_offset_type':'direct','matrix_solver':'GMRES','run_checks':True,'tolerance':1e-10,'max_iterations':1000},
                              'post_processing':{'pressure_rules':{'isentropic':mach>0,'incompressible':mach==0},'pressure_for_forces':'isentropic' if mach else 'incompressible'},
                              'output':{'body_file':'Body.vtk','wake_file':'Wake.vtk','control_point_file':'ControlPoints.vtk','report_file':'Report.json','verbose':True}}
                            (case_folder/'input.json').write_text(input_json(config),encoding='utf-8')
                            proc=execute([machline,'input.json'],case_folder,'solver.log',plan['caseTimeoutSeconds'],plan['threads'])
                            case=parse_machline(case_folder,proc,mach,alpha,plan['beta'],plan,ref)
                        case.update(level=level,path=level+'/'+case_id)
                        case['passed']=case['processCompleted'] and case['iterationConverged'] and case.get('pressureReviewPassed',True)
                        report['cases'].append(case);done+=1;save()
        report['geometryChecked']=all(r['geometryPassed'] for r in report['levels'].values())
        report['solverCompleted']=len(report['cases'])==total and all(c['processCompleted'] for c in report['cases'])
        report['iterationConverged']=report['solverCompleted'] and all(c['iterationConverged'] for c in report['cases'])
        report['convergence']=convergence(report['cases'],plan);report['meshConverged']=report['convergence']['passed']
        report['pressureReviewPassed']=all(c.get('pressureReviewPassed',True) for c in report['cases'])
        report['passed']=all(report[k] for k in ('geometryChecked','solverCompleted','iterationConverged','meshConverged','pressureReviewPassed'))
        report['state']='passed' if report['passed'] else 'rejected'
        report['note']='Подтверждены только перечисленные режимы, постановка и допуски. Сходимость не является проверкой по эксперименту.'
    except InterruptedError:
        report.update(state='cancelled',error='Расчёт отменён; результат не получает допуска.',endedAt=datetime.now(timezone.utc).isoformat());save();write_outputs(folder,report);raise
    except Exception as e:
        report.update(state='error',error=str(e),endedAt=datetime.now(timezone.utc).isoformat());save();write_outputs(folder,report)
        return {'ok':False,'report':report}
    report['endedAt']=datetime.now(timezone.utc).isoformat();save();write_outputs(folder,report);progress('Серия завершена: '+('проверки пройдены' if report['passed'] else 'есть непройденные проверки'),1.)
    return {'ok':True,'report':report}



def write_outputs(folder, report):
    """Readable results and hashes of precisely the files offered for download."""
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    writer.writerow(['level','solver','Mach','alpha_deg','beta_deg','CL','CD','CY','Cl','Cm','Cn','iteration_converged','pressure_review_passed','process_completed','force_model'])
    for c in report.get('cases',[]):
        writer.writerow([c.get(k,'') for k in ('level','solver','mach','alpha','beta')]+[c['coefficients'][k] for k in ('CL','CD','CY','Cl','Cm','Cn')]+[c.get('iterationConverged'),c.get('pressureReviewPassed','not checked'),c.get('processCompleted'),c.get('forceModel')])
    atomic_bytes(Path(folder)/'results.csv',stream.getvalue().encode('utf-8-sig'))
    manifest={}
    for p in sorted(Path(folder).rglob('*')):
        if p.is_file() and not p.is_symlink() and p.name!='artifact_manifest.json' and p.suffix!='.adb':
            manifest[p.relative_to(folder).as_posix()]={'bytes':p.stat().st_size,'sha256':file_digest(p)}
    atomic_bytes(Path(folder)/'artifact_manifest.json',(json.dumps({'format':'section-studio-calculation-files','files':manifest},indent=2)+'\n').encode())


def recover_interrupted(store):
    recovered=[]
    for p in Path(store).glob('*/report.json'):
        if not ID.fullmatch(p.parent.name):continue
        try:
            r=json.loads(p.read_text(encoding='utf-8'))
            if r.get('state')!='running':continue
            r.update(state='interrupted',passed=False,error='Приложение завершилось до окончания серии. Результат не получает допуска; запусти новую серию.')
            atomic_bytes(p,(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
            recovered.append(p.parent.name)
        except (OSError,ValueError):continue
    return recovered


def report_path(store, ident):
    if not isinstance(ident,str) or not ID.fullmatch(ident):
        raise ValueError('Неверный ID расчёта.')
    return Path(store)/ident


def load_report(store, ident):
    p=report_path(store,ident)/'report.json'
    if not p.is_file() or p.stat().st_size>16*1024*1024:
        raise ValueError('Отчёт расчёта не найден.')
    return json.loads(p.read_text(encoding='utf-8'))


def listing(store):
    root=Path(store)
    rows=[]
    if root.is_dir():
        for p in sorted(root.glob('*/report.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:30]:
            try:
                r=load_report(root,p.parent.name)
                rows.append({k:r.get(k) for k in ('id','createdAt','state','passed','sourceHash','geometryChecked','solverCompleted','iterationConverged','meshConverged')})
            except (OSError,ValueError):
                pass
    return rows


def bundle(store, ident):
    folder=report_path(store,ident)
    report=load_report(store,ident)
    if report['state']=='running':
        raise ValueError('Дождись завершения серии или отмени её.')
    write_outputs(folder,report)
    output=folder.parent/(ident+'.zip')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(folder.rglob('*')):
            if p.is_file() and not p.is_symlink() and p.suffix not in ('.adb',):
                z.write(p,p.relative_to(folder).as_posix())
    return output
