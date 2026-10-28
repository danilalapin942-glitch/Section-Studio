"""Explainable MachLine v4.0 geometry preflight, pinned to d62befad.

Exact stop criteria are distinguished from Studio heuristics. No AIC or Cp solve.
The checked/exported MachLine mesh uses feet, regardless of source VSP3 units.
"""
from __future__ import annotations
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
from mesh_audit import inspect_mesh, compare_reports, subtract, cross, dot, norm, MAX_NODES, MAX_FACES

COMMIT = 'd62befad9d2d62e30106440e29862ebac7dc362c'
FORMULATIONS = ('dirichlet-morino', 'dirichlet-source-free', 'neumann-mass-flux', 'neumann-velocity')

def settings(raw=None):
    raw = {} if raw is None else raw
    if not isinstance(raw, dict):
        raise ValueError('Настройки MachLine должны быть объектом.')
    defaults = dict(mach=1.5, alpha=0., beta=0., offset=1e-7)
    s = {}
    for key, default in defaults.items():
        value = raw.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Некорректный параметр MachLine: '+key)
        s[key] = float(value)
    if not 0 <= s['mach'] <= 10 or abs(s['alpha']) > 89 or abs(s['beta']) > 89 or not 0 < s['offset'] <= 10:
        raise ValueError('Проверь число Маха, углы и положительное смещение контрольной точки.')
    s['offsetType'] = raw.get('offsetType', 'direct')
    s['formulation'] = raw.get('formulation', 'dirichlet-morino')
    if s['offsetType'] not in ('direct', 'local') or s['formulation'] not in FORMULATIONS:
        raise ValueError('Неизвестная настройка MachLine.')
    a, b = math.radians(s['alpha']), math.radians(s['beta'])
    s['direction'] = (math.cos(a)*math.cos(b), math.sin(b), math.sin(a)*math.cos(b))
    return s

def read_tri(path, factor=1., tkey=None, components=None):
    components = components or {}
    with Path(path).open(encoding='utf-8') as stream:
        def row():
            text = stream.readline()
            if not text:
                raise ValueError('Оборван TRI-файл.')
            return text.split()
        header = row()
        if len(header) != 2:
            raise ValueError('Нужен ASCII Cart3D TRI: число узлов и треугольников.')
        nv, nf = map(int, header)
        if not 3 <= nv <= MAX_NODES or not 1 <= nf <= MAX_FACES:
            raise ValueError('Предел мини-проверки — 200000 узлов и 150000 треугольников.')
        nodes = []
        for _ in range(nv):
            values=row();p = tuple(float(v)*factor for v in values[:3])
            if len(values) not in (3,4) or len(p) != 3 or not all(math.isfinite(v) and abs(v)<=1e9 for v in p):
                raise ValueError('Неверные координаты TRI.')
            nodes.append(p)
        faces = []
        for _ in range(nf):
            f = [int(v)-1 for v in row()]
            if len(f) != 3 or any(n < 0 or n >= nv for n in f):
                raise ValueError('Неверные индексы треугольника TRI.')
            faces.append(f)
        tags = [int(v) for line in stream for v in line.split()]
        if tags and len(tags) != nf:
            raise ValueError('Число тегов TRI не совпадает с числом панелей.')
        tags = tags or [1]*nf
    names = {}
    if tkey:
        for line in Path(tkey).read_text(encoding='utf-8').splitlines():
            entry = next(csv.reader([line]))
            if len(entry) >= 2 and entry[0].strip().isdigit():
                names[int(entry[0])] = entry[1]
    parts = {}
    for tag in set(tags):
        label = names.get(tag, 'TRI '+str(tag))
        gid = next((i for i in components if label.startswith(i+'_S_')), 'TRI_'+str(tag))
        parts[tag] = dict(part=tag, geom=tag, surface=0, name=components.get(gid, label), geomId=gid,
                          thick=True, plate=0, copy=1, geomCopy=tag)
    return dict(nodes=nodes, faces=faces, faceParts=tags, parts=parts, wakeNodes=set(), refinementLevels=1)

def weld(mesh):
    """MachLine TRI reader merges distances <1e-12 in the exported (ft) units."""
    eps=1e-12; cells=defaultdict(list); nodes=[]; index=[]; visits=0
    for p in mesh['nodes']:
        key=tuple(math.floor(v/eps) for v in p); found=None
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for dz in (-1,0,1):
                    for n in cells.get((key[0]+dx,key[1]+dy,key[2]+dz), ()):
                        visits+=1
                        if visits>2_000_000:raise ValueError('Слишком много совпадающих узлов TRI для полной мини-проверки.')
                        if math.dist(p,nodes[n])<eps:found=n;break
                    if found is not None:break
                if found is not None:break
            if found is not None:break
        if found is None:
            found=len(nodes);nodes.append(p);cells[key].append(found)
        index.append(found)
    return {**mesh,'nodes':nodes,'faces':[[index[n] for n in f] for f in mesh['faces']]},len(index)-len(nodes)

class TriangleTree:
    """BVH for bounded segment crossings; no claim of full intersection proof."""
    def __init__(self,nodes,faces,indices=None):
        self.nodes,self.faces=nodes,faces;indices=list(range(len(faces))) if indices is None else indices
        self.bounds=tuple((min(nodes[n][d] for i in indices for n in faces[i]),max(nodes[n][d] for i in indices for n in faces[i])) for d in range(3))
        self.children=None;self.indices=None
        if len(indices)<=12:self.indices=indices;return
        axis=max(range(3),key=lambda d:self.bounds[d][1]-self.bounds[d][0]);indices.sort(key=lambda i:sum(nodes[n][axis] for n in faces[i]))
        mid=len(indices)//2;self.children=(TriangleTree(nodes,faces,indices[:mid]),TriangleTree(nodes,faces,indices[mid:]))

    def intersect(self,start,disp,exclude,work):
        lo,hi=0.,1.
        for d,(a,b) in enumerate(self.bounds):
            if abs(disp[d])<1e-30:
                if start[d]<a-1e-12 or start[d]>b+1e-12:return None
            else:
                t0,t1=(a-start[d])/disp[d],(b-start[d])/disp[d];lo=max(lo,min(t0,t1));hi=min(hi,max(t0,t1))
                if lo>hi+1e-12:return None
        if self.children:
            for child in self.children:
                hit=child.intersect(start,disp,exclude,work)
                if hit is not None:return hit
            return None
        for i in self.indices:
            work[0]+=1
            if work[0]>2_000_000:raise OverflowError
            if i in exclude:continue
            a,b,c=[self.nodes[n] for n in self.faces[i]];e1,e2=subtract(b,a),subtract(c,a);h=cross(disp,e2);det=dot(e1,h)
            if abs(det)<1e-14*max(1e-30,norm(e1)*norm(e2)*norm(disp)):continue
            r=subtract(start,a);u=dot(r,h)/det
            if u<-1e-10 or u>1+1e-10:continue
            q=cross(r,e1);v=dot(disp,q)/det
            if v<-1e-10 or u+v>1+1e-10:continue
            t=dot(e2,q)/det
            if 1e-8<t<=1+1e-10:return i
        return None

def inspect_machline(raw_mesh, raw_settings=None, meta=None):
    s=settings(raw_settings);mesh,merged=weld(raw_mesh);meta=meta or {}
    report=inspect_mesh(mesh,meta)
    # Reuse generic quality indicators, with solver-specific provenance and limits.
    report.update(kind='machline-tri-preflight',solver='MachLine v4.0',solverCommit=COMMIT,settings=s,meshUnits='ft')
    for issue in report['issues']:
        issue['evidence']='tri-quality-heuristic'
        issue['detail']=issue['detail'].replace('VSPAERO','панельного метода')
    nodes,faces,fp,parts=(mesh[k] for k in ('nodes','faces','faceParts','parts'))
    metrics=[];incident=defaultdict(list);edges=defaultdict(list);groups={}
    def add(code,severity,title,detail,action,ix,value=None,evidence='machline-source-condition'):
        part=fp[ix];key=(code,part);p=parts[part];m=metrics[ix]
        if key not in groups:
            groups[key]=dict(code=code,severity=severity,title=title,detail=detail,action=action,evidence=evidence,
                             component=p['name'],geomId=p['geomId'],part=part,point=m['center'],x=m['center'][0],x0=m['center'][0],x1=m['center'][0],panels=[],_set=set())
        g=groups[key]
        if ix not in g['_set']:g['panels'].append(ix)
        g['_set'].add(ix);g['x0']=min(g['x0'],m['center'][0]);g['x1']=max(g['x1'],m['center'][0])
        if value is not None and value>g.get('metric',-math.inf):g.update(metric=value,point=m['center'],x=m['center'][0])
    for i,f in enumerate(faces):
        p=[nodes[n] for n in f];av=cross(subtract(p[1],p[0]),subtract(p[2],p[1]));length=norm(av);n=tuple(v/(length or 1) for v in av)
        center=tuple(sum(q[d] for q in p)/3 for d in range(3));t=min(1.,abs(dot(n,s['direction'])));q=1-s['mach']**2*t*t
        inclination=math.degrees(math.asin(t));metrics.append(dict(center=center,area=length/2,normal=n,inclination=inclination,q=q))
        for j,node in enumerate(f):incident[node].append(i);edges[tuple(sorted((node,f[(j+1)%3])))].append((i,node<f[(j+1)%3]))
        if length/2<1e-12:
            add('machline_zero_area','error','MachLine: площадь ниже порога STOP','Площадь < 1e−12 ft² в TRI, подготовленном в футах. panel_calc_area завершает работу при этом условии.','Восстанови схлопнутую поверхность или локальную сетку.',i)
        if s['mach']>1 and length:
            if abs(q)<1e-12:add('machline_characteristic','error','MachLine: характеристическая панель','|Q| < 1e−12; преобразование локальных координат завершает работу через STOP.','Исправь форму или постановку расчёта; увеличение offset не меняет наклон панели.',i,inclination)
            elif q<0:add('machline_superinclined','error','MachLine: сверхнаклонная панель','Q = 1−M²(n·c)² < 0. В исследованном исходнике такой треугольник вызывает STOP.','Для локальной неровности пробуй ремонт сечений. Носы, торцы и кромки требуют отдельного решения.',i,inclination)
            elif q<.05:add('machline_near_characteristic','warning','MachLine: близость к характеристическому наклону','0 < Q < 0,05. Множитель преобразования 1/√Q становится большим; порог 0,05 выбран в Studio.','Проверь локальные нормали и чувствительность к сетке; автоматическая смена режима потока отключена.',i,inclination,'tri-quality-heuristic')
    # MachLine has one triangular topology: do not exempt junctions between parts.
    for uses in edges.values():
        if len(uses)>2:
            for i,_ in uses:add('machline_nonmanifold','error','MachLine: более двух соседей ребра','После объединения совпадающих узлов на ребре более двух панелей. Поиск соседей не даёт однозначной пары.','Исправь наложение или согласуй поверхности; удаление произвольных панелей отключено.',i)
        elif len(uses)==2 and uses[0][1]==uses[1][1]:
            add('machline_winding','error','MachLine: несовместимые нормали соседей','Обход общего ребра имеет одно направление на обеих панелях.','Исправь ориентацию исходной поверхности или экспорт.',uses[0][0])
    offset_limited=False;work=[0];normal_failed=0;offset_max=0.;offset_status='not-required' if s['formulation']=='neumann-mass-flux' else 'skipped-degenerate'
    if s['formulation']!='neumann-mass-flux' and not any(m['area']<1e-12 for m in metrics):
        offset_status='nominal-checked'
        tree=TriangleTree(nodes,faces)
        if s['formulation']=='neumann-velocity':
            probes=((i,m['center'],m['normal'],s['offset'],{i}) for i,m in enumerate(metrics))
        else:
            probes=[]
            for node,ixs in incident.items():
                normal=[0.,0.,0.];neighbors=set()
                for i in ixs:
                    other=[n for n in faces[i] if n!=node];a,b=[subtract(nodes[n],nodes[node]) for n in other]
                    theta=math.acos(max(-1.,min(1.,dot(a,b)/(norm(a)*norm(b) or 1.))))
                    for d in range(3):normal[d]+=theta*metrics[i]['normal'][d]
                    neighbors.update(other)
                l=norm(normal)
                if l<1e-12:
                    normal_failed+=1;add('machline_vertex_normal','error','MachLine: нормаль вершины схлопнулась','Угловое усреднение нормалей соседей близко к нулю. Нормирование становится неопределённым.','Проверь перевёрнутую или совпадающую поверхность.',ixs[0]);continue
                avg=sum(math.dist(nodes[node],nodes[n]) for n in neighbors)/max(1,len(neighbors))
                distance=s['offset']*(avg if s['offsetType']=='local' else 1.)
                probes.append((ixs[0],nodes[node],tuple(-v/l for v in normal),distance,set(ixs)))
        try:
            for i,p,d,distance,exclude in probes:
                offset_max=max(offset_max,distance)
                if distance<32*math.ulp(max(1.,*(abs(v) for v in p))):
                    add('machline_offset_roundoff','warning','MachLine: offset близок к точности координат','Смещение меньше 32 ULP масштаба точки. После сложения координат контрольная точка может остаться на поверхности.','Проверь единицы и значение offset. Автоматическая смена настройки отключена.',i,evidence='floating-point-heuristic')
                local=math.sqrt(metrics[i]['area'])
                if distance>.1*local:add('machline_offset_scale','warning','MachLine: большой offset относительно панели','Смещение больше 10% √площади соседней панели. Это эвристика чувствительности контрольной точки.','Проверь единицы и настройку offset; программа не меняет настройки решателя автоматически.',i,distance/max(local,1e-30),'tri-quality-heuristic')
                hit=tree.intersect(p,tuple(v*distance for v in d),exclude,work)
                if hit is not None:add('machline_offset_crossing','warning','MachLine: номинальный offset пересекает поверхность','Отрезок к номинальной контрольной точке пересекает несоседний треугольник. Учтено до правки направления и клонирования вершин в решателе.','Осмотри местную толщину, близкие корпуса и offset; это требует отдельной проверки фактических контрольных точек.',i,evidence='nominal-control-point-heuristic')
        except OverflowError:offset_limited=True;offset_status='limited'
    if s['mach']==1:add('machline_sonic','error','MachLine: M = 1 запрещено','flow_init завершает работу при числе Маха ровно 1.','Задай реальный режим расчёта.',0)
    elif abs(s['mach']-1)<.1:add('machline_transonic','warning','MachLine: близость к звуковому режиму','Порог ±0,1 — предупреждение о применимости линейной модели, не ограничение из исходника.','Проверь физическую применимость метода.',0,evidence='model-applicability-heuristic')
    if s['formulation']=='neumann-velocity' and s['offsetType']=='local':add('machline_offset_type_ignored','info','MachLine: для Neumann velocity offset прямой','В init_neumann тип local не используется для центроидных точек; заданное число считается прямым смещением в ft.','Используй direct для ясной постановки.',0)
    report['issues']+=list(groups.values())
    for issue in report['issues']:
        if '_set' in issue:issue['count']=len(issue.pop('_set'))
    report['issues'].sort(key=lambda i:({'error':0,'warning':1,'info':2}[i['severity']],i['x']))
    for i,issue in enumerate(report['issues']):issue['id']='machmesh-'+str(i)
    report['summary'].update(errors=sum(i['severity']=='error' for i in report['issues']),warnings=sum(i['severity']=='warning' for i in report['issues']),info=sum(i['severity']=='info' for i in report['issues']),mergedNodes=merged,offsetLimited=offset_limited,offsetCandidateTests=work[0],maxOffsetFt=offset_max,normalFailures=normal_failed,superinclinedPanels=sum(m['q']<0 for m in metrics) if s['mach']>1 else 0,characteristicPanels=sum(abs(m['q'])<1e-12 for m in metrics) if s['mach']>1 else 0,minQ=min(m['q'] for m in metrics),machAngleDeg=math.degrees(math.asin(1/s['mach'])) if s['mach']>1 else None)
    report['panelInclinations']=[m['inclination'] for m in metrics]
    report['summary']['offsetStatus']=offset_status
    report['limits']=['Проверена полная объёмная TRI-сетка после экспорта OpenVSP, в футах; профили крыла сохранены.',
                     'Критерии STOP относятся к официальному MachLine v4.0, commit '+COMMIT+'. Для изменённого решателя пределы могут отличаться.',
                     'Контрольные точки номинальные: клонирование на следе и итерационная правка направления MachLine не воспроизводятся.',
                     'Не проверяются матрица влияния, отсутствие влияния на точку, фактическое давление, сходимость и полный набор пересечений.',
                     'Открытый выход сопла может быть намеренным. Плоские торцы, носы и кромки не удаляются и не перестраиваются автоматически.']
    return report

def write_tri(mesh):
    nodes,faces=mesh['nodes'],mesh['faces']
    return f'{len(nodes)} {len(faces)}\n'+''.join(' '.join(format(v,'.17g') for v in p)+'\n' for p in nodes)+''.join(' '.join(str(n+1) for n in f)+'\n' for f in faces)+''.join(str(p)+'\n' for p in mesh['faceParts'])

def compare_machline_reports(before,after):
    family={'machline_superinclined','machline_characteristic','machline_near_characteristic'}
    def normalized(report):
        issues=[i for i in report['issues'] if i['code'] not in family];groups={}
        for i in report['issues']:
            if i['code'] not in family:continue
            key=(i['geomId'],i['part']);g=groups.setdefault(key,{**i,'code':'machline_inclination_family','severity':'warning','count':0,'metric':0.})
            g['count']+=i['count'];g['metric']=max(g['metric'],i.get('metric',0.))
        return {'issues':issues+list(groups.values())}
    out=compare_reports(normalized(before),normalized(after))
    old=defaultdict(int);new=defaultdict(int)
    for r,d in ((before,old),(after,new)):
        for i in r['issues']:
            if i['code'] in family and i['severity']=='error':d[(i['geomId'],i['part'])]+=i['count']
    out += [dict(code='machline_fatal_inclination',geomId=key[0],before=old[key],after=n) for key,n in new.items() if n>old[key]]
    return out

def input_template(report):
    s=report['settings']
    return {'flow':{'freestream_velocity':list(s['direction']),'freestream_mach_number':s['mach']},
            'geometry':{'file':'Mesh.tri','mirror_about':'none','spanwise_axis':'+y','singularity_order':'lower','reference':{'area':1.,'length':1.,'CG':[0.,0.,0.]},'wake_model':{'wake_present':True,'wake_shedding_angle':90.,'trefftz_distance':-1.}},
            'solver':{'formulation':s['formulation'],'control_point_offset':s['offset'],'control_point_offset_type':s['offsetType'],'matrix_solver':'GMRES','run_checks':True},
            'post_processing':{'pressure_rules':{'isentropic':s['mach']>0,'incompressible':s['mach']==0}},
            'output':{'body_file':'Body.vtk','wake_file':'Wake.vtk','control_point_file':'ControlPoints.vtk','report_file':'Report.json','verbose':True}}

def input_json(value):
    """ES30.14E3 in upstream json.f90 requires a decimal point in mantissa.

    Fortran interprets 1e-7 as 1e-21 with that formatted read. Keep JSON numbers.
    """
    def encode(v,depth=0):
        if isinstance(v,float):
            if not math.isfinite(v):raise ValueError('Нужны конечные числа JSON.')
            text=repr(v)
            if 'e' in text and '.' not in text.split('e')[0]:text=text.replace('e','.0e')
            return text
        if isinstance(v,(str,int,bool)) or v is None:return json.dumps(v,ensure_ascii=False)
        if isinstance(v,(list,tuple)):return '['+', '.join(encode(x,depth+1) for x in v)+']'
        return '{\n'+',\n'.join('  '*(depth+1)+json.dumps(k)+': '+encode(x,depth+1) for k,x in v.items())+'\n'+'  '*depth+'}'
    return encode(value)+'\n'
