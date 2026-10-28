"""Native geometry jobs for Section Studio 1.0; no VSPAERO flow solve."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from mesh_audit import read_vspgeom, inspect_mesh, compare_reports
from machline_audit import read_tri, inspect_machline, compare_machline_reports

FACTORS = {'ft': 1., 'm': 1/.3048, 'mm': 1/.3048/1000, 'in': 1/12}


def run_script(executable, folder, script, output):
    (folder/'Prepare.vspscript').write_bytes(script.encode('utf-8'))
    with (folder/'run.log').open('wb') as log:
        try:
            run = subprocess.run([executable, '-script', 'Prepare.vspscript'], cwd=folder,
                                 stdout=log, stderr=subprocess.STDOUT, timeout=180,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as exc:
            raise ValueError('OpenVSP не завершил проверку за 180 секунд. Модель не изменена.') from exc
        except OSError as exc:
            raise ValueError('Не удалось запустить vspscript. Проверь путь и комплект DLL OpenVSP.') from exc
    log = folder/'run.log'
    with log.open('rb') as file:
        first = file.read(10000)
        file.seek(max(0, log.stat().st_size-10000))
        message = (first+file.read(10000)).decode('utf-8', errors='replace')
    target = folder/output
    # Our scripts use int main() and return 0 explicitly. ScriptMgr 3.51 reads
    # GetReturnDWord even for void main(), whose status can be indeterminate.
    if run.returncode != 0 or 'SECTION_STUDIO_ERROR' in message or f'SECTION_STUDIO_SAVED: {output}' not in message or not target.is_file():
        raise ValueError('OpenVSP не подтвердил проверку.\n'+message[-6000:])
    if target.stat().st_size > 64*1024*1024:
        raise ValueError('Результат проверки превышает 64 МБ.')
    return target


def metadata(xml):
    root = ET.fromstring(xml)
    nodes = root.findall('./Vehicle/Geom')
    engine = {}
    for geom in nodes:
        gid = geom.findtext('ParmContainer/ID')
        node = geom.find('ParmContainer/EngineModel/GeomIOType')
        engine[gid] = int(float(node.get('Value', '0'))) if node is not None else 0
    mgr = root.find('./Vehicle/VSPAEROMgr')
    if mgr is None:
        mgr = root.find('.//VSPAEROMgr')
    symmetry = False
    if mgr is not None:
        for node in mgr.iter('Symmetry'):
            symmetry = node.get('Value', '0') != '0.000000000000000000e+00' and float(node.get('Value', '0')) != 0
    return {'engine': engine, 'symmetry': symmetry, 'components': {g.findtext('ParmContainer/ID'): g.findtext('ParmContainer/Name') for g in nodes}}


def build_mesh(executable, package_root, xml, units, preset):
    script = (package_root/'native/mesh.vspscript').read_text(encoding='utf-8').replace('SS_PRESET', '1' if preset == 'hybrid' else '0')
    with tempfile.TemporaryDirectory(prefix='StudioMesh_') as name:
        folder = Path(name)
        (folder/'Source.vsp3').write_bytes(xml.encode('utf-8'))
        output = run_script(executable, folder, script, 'MeshInfo.txt')
        lines = output.read_text(encoding='utf-8').splitlines()
        if len(lines) != 6:
            raise ValueError('OpenVSP не вернул описание сетки.')
        mesh_path = Path(lines[3]).resolve()
        if mesh_path.parent != folder.resolve() or mesh_path.suffix != '.vspgeom' or not mesh_path.is_file():
            raise ValueError('OpenVSP не сформировал ожидаемый файл сетки.')
        if mesh_path.stat().st_size > 64*1024*1024:
            raise ValueError('Для мини-проверки предел сетки — 64 МБ.')
        key_path = mesh_path.with_suffix('.vkey')
        if not key_path.is_file() or key_path.stat().st_size > 2*1024*1024:
            raise ValueError('Отсутствует таблица компонентов vkey.')
        mesh = read_vspgeom(mesh_path, key_path, FACTORS[units])
        meta = metadata(xml)
        meta['symmetry'] = bool(int(lines[5]))
        report = inspect_mesh(mesh, meta)
        included = {p['geomId'] for p in mesh['parts'].values()}
        report.update(openVSPVersion=lines[0], thickSet=int(lines[1]), thinSet=int(lines[2]), useMode=bool(int(lines[4])), symmetry=bool(int(lines[5])), preset=preset,
                      sourceUnits=units, sourceHash=hashlib.sha256(xml.encode('utf-8')).hexdigest(),
                      excludedComponents=[{'geomId': gid, 'name': n} for gid, n in meta['components'].items() if gid not in included])
        return report


def build_machline_mesh(executable, package_root, xml, units, solver_settings=None):
    script = (package_root/'native/machline_mesh.vspscript').read_text(encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='StudioMachLine_') as name:
        folder=Path(name);(folder/'Source.vsp3').write_bytes(xml.encode('utf-8'))
        info=run_script(executable,folder,script,'MachInfo.txt')
        tri,key=folder/'MachMesh.tri',folder/'MachMesh.tkey'
        if not tri.is_file() or not key.is_file() or tri.stat().st_size>64*1024*1024 or key.stat().st_size>2*1024*1024:
            raise ValueError('OpenVSP не сформировал ожидаемую TRI-сетку.')
        meta=metadata(xml);mesh=read_tri(tri,FACTORS[units],key,meta['components'])
        report=inspect_machline(mesh,solver_settings,meta)
        included={p['geomId'] for p in mesh['parts'].values()}
        if any(gid.startswith('TRI_') for gid in included):
            raise ValueError('Не удалось сопоставить TRI-поверхности компонентам VSP3.')
        report.update(openVSPVersion=info.read_text(encoding='utf-8').strip(),thickSet=-1,thinSet=-1,useMode=False,symmetry=False,preset='machline',
                      sourceUnits=units,sourceHash=hashlib.sha256(xml.encode('utf-8')).hexdigest(),
                      excludedComponents=[{'geomId':gid,'name':n} for gid,n in meta['components'].items() if gid not in included])
        return report


def finite_pair(value, label):
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in value) or value[1] <= value[0]:
        raise ValueError('Неверный диапазон '+label+'.')
    return value


def canonical(node):
    if node is None:
        return None
    # XMLSerializer and OpenVSP use different numeric spellings ("12" vs "1.2e1").
    # Normalize only numeric Value attributes; IDs and all other strings remain exact.
    attributes = dict(node.attrib)
    if 'Value' in attributes:
        try:
            value = float(attributes['Value'])
            if math.isfinite(value):
                attributes['Value'] = format(value, '.12g')
        except ValueError:
            pass
    return (node.tag, tuple(sorted(attributes.items())), (node.text or '').strip(), tuple(canonical(n) for n in node))


def check_repair_invariants(original, candidate, gid, geoms):
    old, new = geoms(original), geoms(candidate)
    if gid not in old or old[gid][0].lower() != 'fuselage' or set(old) != set(new):
        raise ValueError('Ремонт допускается для одного существующего FUSELAGE.')
    a, b = old[gid][1]; c, d = new[gid][1]
    if original[:a]+original[b:] != candidate[:c]+candidate[d:]:
        raise ValueError('Ремонт изменяет другие компоненты или настройки модели.')
    base = ET.fromstring(original[a:b]); result = ET.fromstring(candidate[c:d])
    for path in ('ParmContainer', 'GeomBase'):
        if canonical(base.find(path)) != canonical(result.find(path)):
            raise ValueError('Положение, длина, наборы или режим двигателя изменились; ремонт отклонён.')
    ss = base.findall('FuselageGeom/XSecSurf/XSec'); tt = result.findall('FuselageGeom/XSecSurf/XSec')
    if len(ss) != len(tt):
        raise ValueError('Ремонт не должен добавлять или удалять станции.')
    for s, t in zip(ss, tt):
        for parm in ('XLocPercent', 'RefLength', 'XRotate', 'YRotate', 'ZRotate'):
            p = 'ParmContainer/XSec/'+parm
            a, b = s.find(p), t.find(p)
            if a is None and b is None:
                continue
            if a is None or b is None or abs(float(a.get('Value'))-float(b.get('Value'))) > 1e-12:
                raise ValueError('Продольные координаты или повороты станций изменились; ремонт отклонён.')


def sample_body(executable, package_root, xml, gid, factor):
    script = (package_root/'native/repair_sample.vspscript').read_text(encoding='utf-8').replace('SS_BODY', gid)
    with tempfile.TemporaryDirectory(prefix='StudioRepair_') as name:
        folder = Path(name)
        (folder/'Source.vsp3').write_bytes(xml.encode('utf-8'))
        file = run_script(executable, folder, script, 'Samples.txt')
        with file.open(encoding='utf-8') as stream:
            surfaces = int(stream.readline())
            points = [tuple(float(v)*factor for v in line.split()) for line in stream]
        if not 1 <= surfaces <= 16 or len(points) != surfaces*321*65 or any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in points):
            raise ValueError('Некорректная выборка поверхности ремонта.')
        return points


def verify_repair(executable, package_root, data, geoms):
    original, candidate, gid = data.get('xml'), data.get('candidateXml'), data.get('bodyId')
    if not isinstance(gid, str) or gid not in geoms(original):
        raise ValueError('Нет выбранного тела ремонта.')
    check_repair_invariants(original, candidate, gid, geoms)
    units, preset = data['units'], data['preset']
    budget = data.get('budget')
    if not isinstance(budget, (int, float)) or not math.isfinite(budget) or not 0 < budget <= 10:
        raise ValueError('Неверный предел смещения ремонта.')
    zone = finite_pair(data.get('zone'), 'ремонта')
    protected = data.get('protectedZones', [])
    if not isinstance(protected, list) or len(protected) > 64:
        raise ValueError('Неверные защищённые зоны.')
    protected = [finite_pair(p, 'защиты') for p in protected]
    machline=data.get('solver')=='machline'
    def build(xml):
        return build_machline_mesh(executable,package_root,xml,units,data.get('machline')) if machline else build_mesh(executable,package_root,xml,units,preset)
    before = build(original)
    if before['useMode']:
        raise ValueError('Mode может переопределять геометрию. Для проверки локального ремонта выбери гибридный режим без Mode.')
    if not any(p['geomId'] == gid and p['thick'] for p in before['mesh']['parts']):
        raise ValueError('Для проверки ремонта выбранное тело должно входить в объёмную сетку. Выбери гибридный режим или исправь наборы в VSP3.')
    after = build(candidate)
    a = sample_body(executable, package_root, original, gid, FACTORS[units])
    b = sample_body(executable, package_root, candidate, gid, FACTORS[units])
    if len(a) != len(b):
        raise ValueError('Число поверхностей после ремонта изменилось.')
    maximum = outside = protected_move = 0.
    for p, q in zip(a, b):
        distance = math.dist(p, q); maximum = max(maximum, distance)
        if not zone[0]-1e-7 <= p[0] <= zone[1]+1e-7:
            outside = max(outside, distance)
        if any(lo-1e-7 <= p[0] <= hi+1e-7 for lo, hi in protected):
            protected_move = max(protected_move, distance)
    reasons = []
    if maximum < 1e-8:
        reasons.append('Native-поверхность практически не изменилась; применение связей могло отменить правку.')
    if maximum > budget*1.001+1e-7:
        reasons.append('Фактическое смещение поверхности превышает предел.')
    if outside > 1e-6:
        reasons.append('Сглаживание распространяет изменение за пределы разрешённой зоны.')
    if protected_move > 1e-7:
        reasons.append('Изменена защищённая зона сопряжения.')
    introduced = compare_machline_reports(before, after) if machline else compare_reports(before, after)
    if before['summary']['proximityLimited'] or after['summary']['proximityLimited']:
        reasons.append('Поиск близких панелей достиг ограничения; проверка ремонта неполная.')
    target_before=target_after=None
    if machline:
        if before['summary']['offsetLimited'] or after['summary']['offsetLimited']:
            reasons.append('Проверка смещения контрольных точек неполная; ремонт отклонён.')
        if any(r['summary']['offsetStatus']=='skipped-degenerate' for r in (before,after)):
            reasons.append('Вырожденные панели не позволили проверить контрольные точки; ремонт отклонён.')
        if str(data.get('code','')).startswith('machline_'):
            def target(report):
                mesh=report['mesh'];parts={p['part']:p for p in mesh['parts']};values=[]
                for i,face in enumerate(mesh['faces']):
                    x=sum(mesh['nodes'][n][0] for n in face)/len(face)
                    if parts[mesh['faceParts'][i]]['geomId']==gid and zone[0]<=x<=zone[1]:values.append(report['panelInclinations'][i])
                return max(values) if values else None
            target_before,target_after=target(before),target(after)
            if target_before is None or target_after is None or target_before-target_after<max(.05,.02*target_before):
                reasons.append('В реальной TRI-сетке наклон выбранной зоны не снизился хотя бы на 2% (минимум 0,05°).')
    if introduced:
        reasons.append('В реальной входной сетке появились новые или усилились прежние предупреждения.')
    return {'ok': True, 'verified': not reasons, 'reasons': reasons, 'before': before, 'after': after,
            'nativeMaxMoveFt': maximum, 'nativeOutsideMoveFt': outside, 'protectedMoveFt': protected_move,
            'sampling': {'u': 321, 'w': 65, 'points': len(a), 'limit': 'Конечная выборка; тонкие изменения между отсчётами могут быть пропущены.'},
            'introduced': introduced, 'candidateHash': after['sourceHash'],
            'solver':'MachLine' if machline else 'VSPAERO','inclinationBefore':target_before,'inclinationAfter':target_after}
