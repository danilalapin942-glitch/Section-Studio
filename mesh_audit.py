"""Geometric preflight of the first (fine) VSPAERO v3 input mesh, stdlib only.

This is not the solver's subsequent simplified/agglomerated mesh or a Cp solve.
All thresholds below are application heuristics and are reported as such.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import math
from pathlib import Path
import statistics

MAX_NODES = 200_000
MAX_FACES = 150_000


def subtract(a, b):
    return tuple(x-y for x, y in zip(a, b))


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def norm(a):
    return math.sqrt(dot(a, a))


def angle(a, b):
    return math.degrees(math.acos(max(-1., min(1., dot(a, b)/(norm(a)*norm(b) or 1.)))))


def read_vkey(path):
    lines = Path(path).read_text(encoding='utf-8').splitlines()
    if not lines or 'v3' not in lines[0].lower():
        raise ValueError('Нужен vkey v3 из OpenVSP 3.51.')
    start = next((k for k, v in enumerate(lines) if v.startswith('# part#')), None)
    if start is None:
        raise ValueError('В vkey нет описания поверхностей.')
    parts = {}
    for row in csv.reader(lines[start+1:]):
        if not row or not row[0].strip():
            break
        if len(row) < 9:
            raise ValueError('Повреждена таблица поверхностей vkey.')
        p, geom, surface, name, gid, thick, plate, copy, geomcopy = row[:9]
        parts[int(p)] = {'part': int(p), 'geom': int(geom), 'surface': int(surface), 'name': name,
                         'geomId': gid, 'thick': bool(int(thick)), 'plate': int(plate),
                         'copy': int(copy), 'geomCopy': int(geomcopy)}
    # Surface metadata uses tags, which can differ from part IDs for subsurfaces.
    tag_start = next((k for k, v in enumerate(lines) if v.startswith('# tag#')), None)
    tags = {}
    if tag_start is not None:
        for row in csv.reader(lines[tag_start+1:]):
            if not row or not row[0].strip():
                break
            if len(row) < 2:
                raise ValueError('Повреждена таблица тегов vkey.')
            tags[int(row[0])] = int(row[1])
    return parts, tags


def read_vspgeom(path, vkey, factor=1.):
    parts, tags = read_vkey(vkey)
    with Path(path).open(encoding='utf-8') as file:
        def line():
            value = file.readline()
            if not value:
                raise ValueError('Оборван файл vspgeom.')
            return value.strip()
        if line().lower() != '# vspgeom v3':
            raise ValueError('Поддерживается vspgeom v3 из OpenVSP 3.51.')
        levels = int(line())
        counts = line().split()
        if len(counts) != 3 or levels < 1:
            raise ValueError('Некорректный заголовок vspgeom.')
        count, face_count, _wake_count = map(int, counts)
        if not 3 <= count <= MAX_NODES or not 1 <= face_count <= MAX_FACES:
            raise ValueError('Для мини-проверки предел — 200000 узлов и 150000 панелей; нужна более редкая сетка.')
        nodes = []
        for _ in range(count):
            row = tuple(float(v)*factor for v in line().split())
            if len(row) != 3 or not all(math.isfinite(v) for v in row):
                raise ValueError('В сетке есть неверные координаты.')
            nodes.append(row)
        if int(line()) != face_count:
            raise ValueError('Не совпало число панелей в vspgeom.')
        faces = []
        for _ in range(face_count):
            row = [int(v) for v in line().split()]
            if not row or not 3 <= row[0] <= 128 or len(row) != row[0]+1 or any(n < 1 or n > count for n in row[1:]):
                raise ValueError('Повреждена связность панелей vspgeom.')
            faces.append([n-1 for n in row[1:]])
        face_parts = []
        for face in faces:
            row = line().split()
            if len(row) != 2+2*len(face):
                raise ValueError('Повреждены UV-данные vspgeom.')
            tag = int(row[0])
            part = tags.get(tag, tag)
            if part not in parts:
                raise ValueError('Панель не найдена в таблице vkey.')
            face_parts.append(part)
        for _ in faces:
            if len(line().split()) != 2:
                raise ValueError('Повреждена таблица родительских панелей.')
        wake_count = int(line())
        wake_nodes = set()
        for _ in range(wake_count):
            row = line().split()
            if len(row) < 2:
                raise ValueError('Повреждён заголовок кромки следа.')
            count = abs(int(row[0]))
            indices = [int(v)-1 for v in row[2:]]
            while len(indices) < count:
                indices.extend(int(v)-1 for v in line().split())
            if len(indices) != count or any(n < 0 or n >= len(nodes) for n in indices):
                raise ValueError('Неверные узлы кромки следа.')
            wake_nodes.update(indices)
    return {'nodes': nodes, 'faces': faces, 'faceParts': face_parts, 'parts': parts,
            'wakeNodes': wake_nodes, 'refinementLevels': levels}


def inspect_mesh(mesh, source_meta=None):
    nodes, faces, fp, parts = (mesh[k] for k in ('nodes', 'faces', 'faceParts', 'parts'))
    source_meta = source_meta or {}
    diag = norm(tuple(max(p[d] for p in nodes)-min(p[d] for p in nodes) for d in range(3)))
    eps = max(1e-10, diag*1e-10)
    edges = defaultdict(list)
    duplicate, centers, groups, metrics = {}, {}, {}, []
    codes = defaultdict(set)
    def add(code, severity, title, detail, action, ix, value=None, other=None):
        part = fp[ix]; key = (code, part, fp[other] if other is not None else 0)
        m = metrics[ix]; p = parts[part]
        codes[code].add(ix)
        if key not in groups:
            groups[key] = {'code': code, 'severity': severity, 'title': title, 'detail': detail,
                           'action': action, 'evidence': 'native-vspgeom-input', 'component': p['name'],
                           'geomId': p['geomId'], 'part': part, 'point': list(m['center']), 'x': m['center'][0],
                           'x0': m['center'][0], 'x1': m['center'][0], 'face': ix, 'panels': [],
                           'otherComponent': parts[fp[other]]['name'] if other is not None else None, '_indices': set()}
        g = groups[key]
        g['_indices'].add(ix)
        g['x0'] = min(g['x0'], m['center'][0]); g['x1'] = max(g['x1'], m['center'][0])
        if len(g['panels']) < 500:
            g['panels'].append(ix)
        if value is not None and (g.get('metric') is None or value > g['metric']):
            g['metric'] = value; g['point'] = list(m['center']); g['x'] = m['center'][0]; g['face'] = ix
    for ix, face in enumerate(faces):
        xyz = [nodes[n] for n in face]
        center = tuple(sum(v[d] for v in xyz)/len(xyz) for d in range(3))
        av = [0., 0., 0.]
        for j in range(1, len(xyz)-1):
            c = cross(subtract(xyz[j], xyz[0]), subtract(xyz[j+1], xyz[0]))
            av = [a+b*.5 for a, b in zip(av, c)]
        area = norm(av); normal = tuple(v/(area or 1.) for v in av)
        lengths = [norm(subtract(xyz[(j+1) % len(xyz)], xyz[j])) for j in range(len(xyz))]
        longest = max(lengths)
        aspect = longest*longest/(2*area) if area else 1e30
        warp = max(abs(dot(subtract(v, xyz[0]), normal)) for v in xyz)/(longest or 1.)
        metrics.append({'center': center, 'area': area, 'normal': normal, 'aspect': aspect})
        if len(set(face)) < len(face) or area <= max(eps*eps, longest*longest*1e-12):
            add('mesh_degenerate', 'error', 'Вырожденная панель', 'Повторные узлы или почти нулевая площадь панели. Площадь входит в восстановление градиентов и перепада давления.', 'Исправь схлопнутую геометрию или сетку и повтори проверку.', ix)
        elif aspect > 100:
            add('mesh_sliver', 'warning', 'Очень вытянутая панель', 'Отношение максимального ребра в квадрате к удвоенной площади превышает 100. Это порог Studio, не допуск VSPAERO.', 'Осмотри короткие переходы, пересечения и распределение сетки; не сглаживай намеренную кромку автоматически.', ix, aspect)
        if warp > .1:
            add('mesh_warped', 'warning', 'Неплоская многоугольная панель', 'Отклонение узла от плоскости нормали превышает 10% самого длинного ребра.', 'Уточни форму или разбивку панели и повтори проверку.', ix, warp)
        signature = tuple(sorted(tuple(round(v/eps) for v in p) for p in xyz))
        if signature in duplicate:
            add('mesh_duplicate', 'error', 'Совпадающие панели', 'Геометрически совпадающие панели обнаружены даже при разных ID узлов.', 'Удаление из файла сетки не выполняется: устрани дублирующий компонент в OpenVSP.', ix, other=duplicate[signature])
        else:
            duplicate[signature] = ix
        center_key = tuple(round(v/eps) for v in center)
        if area > eps*eps:
            for other in centers.get(center_key, ()):
                if norm(subtract(center, metrics[other]['center'])) < eps*2:
                    add('mesh_coincident_centers', 'error', 'Совпадающие центры панелей', 'Разные панели имеют практически один центр. Обратное расстояние центров входит в восстановление градиента VSPAERO.', 'Проверь наложение, складку или дублирование исходных поверхностей.', ix, other=other)
            representatives = centers.setdefault(center_key, [])
            if len(representatives) < 4:
                representatives.append(ix)
        for j, n in enumerate(face):
            m = face[(j+1) % len(face)]; edges[tuple(sorted((n, m)))].append((ix, n < m))
    for edge, uses in edges.items():
        if len(uses) == 1:
            ix = uses[0][0]; part = parts[fp[ix]]
            if not part['thick'] or all(n in mesh['wakeNodes'] for n in edge):
                continue
            if source_meta.get('symmetry') and all(abs(nodes[n][1]) <= eps*10 for n in edge):
                continue
            engine = bool(source_meta.get('engine', {}).get(part['geomId']))
            add('mesh_open_thick_boundary', 'info' if engine else 'warning', 'Открытое ребро объёмной поверхности',
                'Двигательная граница требует осмотра; тип отверстия автоматически не классифицирован.' if engine else 'У объёмной поверхности найдено ребро с одной панелью; это может быть отверстие, несогласованный стык или допустимая обрезка.',
                'Проверь назначение границы и граничные условия в OpenVSP. Границы тонких поверхностей и узлы следа учитываются отдельно.', ix)
        elif len(uses) == 2:
            (i, si), (j, sj) = uses
            if fp[i] != fp[j]:
                continue
            if si == sj:
                add('mesh_winding', 'error', 'Несогласованный обход панелей', 'Соседние панели одного участка обходят общее ребро в одном направлении; нормали могут быть обращены.', 'Исправь ориентацию или складку исходной поверхности.', i, other=j)
            a, b = metrics[i], metrics[j]
            if a['area'] <= eps*eps or b['area'] <= eps*eps:
                continue
            ratio = max(a['area'], b['area'])/min(a['area'], b['area'])
            if ratio > 50:
                add('mesh_area_jump', 'warning', 'Резкий скачок площади соседних панелей', 'Площади соседей различаются больше чем в 50 раз. В VSPAERO отношение площадей участвует в весах восстановления градиента.', 'Осмотри локальную сетку у стыка и устрани случайное чрезмерное сгущение.', i, ratio, other=j)
            theta = angle(a['normal'], b['normal'])
            if theta > 75 and not any(n in mesh['wakeNodes'] for n in edge):
                add('mesh_normal_jump', 'warning', 'Резкий поворот нормалей', 'Нормали соседних панелей одного участка различаются больше чем на 75°. Намеренные грани и торцы требуют интерпретации.', 'Сопоставь с замыслом геометрии. Не скругляй грань только ради удаления предупреждения.', i, theta, other=j)
        elif max(Counter(fp[ix] for ix, _ in uses).values()) > 2:
            add('mesh_nonmanifold', 'error', 'Неоднозначная связность участка', 'К одному ребру относятся более двух панелей одной поверхности. Стыки разных частей гибридной сетки не считаются таким дефектом.', 'Проверь дублирующиеся поверхности и самопересечения.', uses[0][0])
    # A bounded centroid proximity check, not a triangle intersection algorithm.
    sizes = [math.sqrt(m['area']) for m in metrics if m['area'] > eps*eps]
    cell = max(eps*100, statistics.median(sizes) if sizes else 1.)
    grid = defaultdict(list)
    for i, m in enumerate(metrics):
        grid[tuple(math.floor(v/cell) for v in m['center'])].append(i)
    pairs, tested, visits, limited = set(), 0, 0, False
    for i, a in enumerate(metrics):
        r = .15*math.sqrt(a['area']); c = tuple(math.floor(v/cell) for v in a['center'])
        steps = math.ceil(r/cell)
        if steps > 4:
            limited = True; continue
        for x in range(c[0]-steps, c[0]+steps+1):
            for y in range(c[1]-steps, c[1]+steps+1):
                for z in range(c[2]-steps, c[2]+steps+1):
                    for j in grid.get((x, y, z), ()):
                        visits += 1
                        if visits > 2_000_000:
                            limited = True; break
                        if j == i or fp[i] == fp[j] or parts[fp[i]]['geomCopy'] == parts[fp[j]]['geomCopy'] or set(faces[i]).intersection(faces[j]):
                            continue
                        tested += 1
                        b = metrics[j]; scale = min(math.sqrt(a['area']), math.sqrt(b['area']))
                        distance = norm(subtract(a['center'], b['center']))
                        if scale > eps and distance < .15*scale:
                            key = tuple(sorted((i, j)))
                            if key in pairs:
                                continue
                            pairs.add(key)
                            add('mesh_near_centers', 'warning', 'Слишком близкие центры несвязанных панелей', 'Расстояние центров меньше 15% меньшего размера √площади. Это локальный индикатор чувствительности, а не точный зазор поверхностей.', 'Проверь сохранённый зазор и местную сетку; размах и положение крыла автоматически не изменяются.', i, scale/max(distance, eps), other=j)
                    if visits > 2_000_000:
                        break
                if visits > 2_000_000:
                    break
            if visits > 2_000_000:
                break
        if visits > 2_000_000:
            break
    issues = list(groups.values())
    issues.sort(key=lambda i: ({'error': 0, 'warning': 1, 'info': 2}[i['severity']], i['x']))
    for n, issue in enumerate(issues):
        issue['id'] = f'mesh-{n}'
        issue['count'] = len(issue.pop('_indices'))
    areas = [m['area'] for m in metrics]
    return {'kind': 'vspaero-input-mesh', 'units': 'ft', 'aerodynamicSolverRun': False, 'cpCalculated': False,
            'issues': issues, 'summary': {'nodes': len(nodes), 'panels': len(faces), 'parts': len(parts),
            'thickParts': sum(p['thick'] for p in parts.values()), 'thinParts': sum(not p['thick'] for p in parts.values()),
            'minAreaFt2': min(areas), 'maxAspect': max(m['aspect'] for m in metrics),
            'refinementLevels': mesh['refinementLevels'], 'errors': sum(i['severity'] == 'error' for i in issues),
            'warnings': sum(i['severity'] == 'warning' for i in issues), 'info': sum(i['severity'] == 'info' for i in issues),
            'proximityPairsTested': tested, 'proximityCandidateVisits': visits, 'proximityLimited': limited},
            'settings': {'aspect': 100, 'areaRatio': 50, 'normalAngleDeg': 75, 'warpFraction': .1, 'centerDistanceRatio': .15, 'coordinateEpsilonFt': eps},
            'limits': ['Проверена первая входная сетка vspgeom v3 после пересечений и обрезок OpenVSP.',
            'VSPAERO затем упрощает и агломерирует сетку; эти уровни решателя здесь не строятся.',
            'Поиск близких центров не является полным поиском пересечений или минимального зазора треугольников.',
            'Пороговые значения — эвристики Section Studio, не допуски OpenVSP.',
            'Сходящаяся сетка и отсутствие предупреждений не гарантируют корректное давление, отрыв или трансзвуковое течение.'],
            'mesh': {'nodes': nodes, 'faces': faces, 'faceParts': fp, 'parts': list(parts.values())}}


def compare_reports(before, after):
    """Accept no new error/warning class and no increase in flagged panel counts."""
    def counts(report):
        out = Counter()
        for issue in report['issues']:
            if issue['severity'] in ('error', 'warning'):
                out[(issue['code'], issue['geomId'], issue['part'])] += issue['count']
        return out
    a, b = counts(before), counts(after)
    increased = [{'code': key[0], 'geomId': key[1], 'before': a[key], 'after': n}
                 for key, n in b.items() if n > a[key]]
    for issue in after['issues']:
        if issue['severity'] not in ('error', 'warning') or 'metric' not in issue:
            continue
        old = [i['metric'] for i in before['issues'] if 'metric' in i and i['code'] == issue['code'] and i['geomId'] == issue['geomId'] and i['part'] == issue['part']]
        if old and issue['metric'] > max(old)*1.02:
            increased.append({'code': issue['code'], 'geomId': issue['geomId'], 'metricBefore': max(old), 'metricAfter': issue['metric']})
    return increased
