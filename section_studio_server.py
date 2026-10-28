"""Local Section Studio launcher. Python 3.10+, standard library only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import xml.etree.ElementTree as ET
from native_audit import build_mesh, build_machline_mesh, verify_repair, FACTORS
from machline_audit import settings as machline_settings, read_tri, inspect_machline

ROOT = Path(__file__).resolve().parent
MAX_INPUT = 64 * 1024 * 1024


def validate_executable(value):
    path = Path(str(value).strip().strip('"')).expanduser()
    if path.is_dir():
        path = path / ('vspscript.exe' if os.name == 'nt' else 'vspscript')
    if path.name.lower() not in ('vspscript.exe', 'vspscript') or not path.is_file():
        raise ValueError('Выбери vspscript.exe из папки OpenVSP, а не vsp.exe.')
    if os.name != 'nt' and not os.access(path, os.X_OK):
        raise ValueError('У vspscript нет разрешения на запуск.')
    return str(path.resolve())


def geoms(xml):
    if not isinstance(xml, str) or len(xml.encode('utf-8')) > 40_000_000:
        raise ValueError('Предел VSP3 — 40 МБ.')
    if re.search(r'<!DOCTYPE|<!ENTITY', xml, re.I):
        raise ValueError('XML с DTD или сущностями не поддерживается.')
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError('Некорректный XML VSP3.') from exc
    if root.tag != 'Vsp_Geometry':
        raise ValueError('Нужен файл VSP3 из OpenVSP 3.')
    nodes = root.findall('./Vehicle/Geom')
    stack, ranges, start = [], [], None
    pattern = r'<!--[\s\S]*?-->|<\?[\s\S]*?\?>|</?([A-Za-z_][\w:.-]*)\b[^>]*>'
    for match in re.finditer(pattern, xml):
        tag = match.group(1)
        if not tag:
            continue
        text = match.group(0)
        if text.startswith('</'):
            if tag == 'Geom' and stack == ['Vsp_Geometry', 'Vehicle', 'Geom']:
                ranges.append((start, match.end()))
            if stack:
                stack.pop()
        else:
            if tag == 'Geom' and stack == ['Vsp_Geometry', 'Vehicle']:
                start = match.start()
            if not text.endswith('/>'):
                stack.append(tag)
    if len(nodes) != len(ranges):
        raise ValueError('Не удалось выделить компоненты VSP3.')
    result = {}
    for node, bounds in zip(nodes, ranges):
        ident = node.findtext('ParmContainer/ID', '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_]{1,40}', ident) or ident in result:
            raise ValueError('Некорректные или повторяющиеся ID компонентов.')
        result[ident] = (node.findtext('GeomBase/TypeName', ''), bounds)
    return result


def merge_selected(original, converted, selection):
    old, new = geoms(original), geoms(converted)
    for ident in sorted(selection, key=lambda item: old[item][1][0], reverse=True):
        if ident not in new:
            raise ValueError('OpenVSP не сохранил выбранный компонент.')
        lo, hi = old[ident][1]
        a, b = new[ident][1]
        original = original[:lo] + converted[a:b] + original[hi:]
    return original


class Studio(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, config, executable=None, port=0):
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = f'http://127.0.0.1:{self.server_port}'
        self.token = secrets.token_urlsafe(32)
        self.config_path = Path(config)
        self.busy = threading.Lock()
        self.executable = None
        if executable:
            self.executable = validate_executable(executable)
        else:
            try:
                stored = json.loads(self.config_path.read_text(encoding='utf-8'))
                self.executable = validate_executable(stored.get('executable'))
            except (OSError, ValueError, TypeError):
                candidate = shutil.which('vspscript')
                if candidate:
                    self.executable = validate_executable(candidate)

    def audit(self, data, repair=False):
        geoms(data.get('xml'))
        if data.get('units') not in ('ft', 'm', 'mm', 'in') or data.get('preset') not in ('source', 'hybrid'):
            raise ValueError('Проверь единицы и режим сетки.')
        if repair:
            geoms(data.get('candidateXml'))
        if data.get('solver', 'vspaero') not in ('vspaero','machline'):
            raise ValueError('Неизвестный решатель проверки.')
        if data.get('solver')=='machline':
            machline_settings(data.get('machline'))
        if not self.busy.acquire(blocking=False):
            raise ValueError('OpenVSP занят. Дождись завершения текущей задачи.')
        try:
            if not self.executable:
                raise ValueError('Сначала выбери vspscript.exe кнопкой «Настроить OpenVSP».')
            if repair:
                return verify_repair(self.executable, ROOT, data, geoms)
            if data.get('solver')=='machline':
                return {'ok':True,'report':build_machline_mesh(self.executable,ROOT,data['xml'],data['units'],data.get('machline'))}
            return {'ok': True, 'report': build_mesh(self.executable, ROOT, data['xml'], data['units'], data['preset'])}
        finally:
            self.busy.release()

    def prepare(self, data):
        xml, kind = data.get('xml'), data.get('kind')
        source = geoms(xml)
        if kind == 'sections':
            chosen = data.get('selection')
            if not isinstance(chosen, list) or len(chosen) != 2 or len(set(chosen)) != 2:
                raise ValueError('Выбери два разных компонента FUSELAGE.')
            if any(not isinstance(i, str) or i not in source or source[i][0].lower() != 'fuselage' for i in chosen):
                raise ValueError('Выбранный компонент не является FUSELAGE.')
            script = (ROOT / 'native/sections.vspscript').read_text(encoding='utf-8')
            script = script.replace('"SS_SELECTED"', ','.join(json.dumps(i) for i in chosen))
            output = 'Source_prepared.vsp3'
        elif kind == 'wings':
            units = data.get('units')
            if units not in ('ft', 'm', 'mm', 'in'):
                raise ValueError('Проверь единицы модели.')
            if not any(v[0].lower() == 'wing' for v in source.values()):
                raise ValueError('В модели нет компонента Wing.')
            script = (ROOT / f'native/wings_{units}.vspscript').read_text(encoding='utf-8')
            output = 'WingData.json'
        else:
            raise ValueError('Неизвестный вид подготовки.')
        if not self.busy.acquire(blocking=False):
            raise ValueError('OpenVSP занят подготовкой. Дождись завершения.')
        try:
            if not self.executable:
                raise ValueError('Сначала выбери vspscript.exe кнопкой «Настроить OpenVSP».')
            with tempfile.TemporaryDirectory(prefix='SectionStudio_') as name:
                folder = Path(name)
                (folder / 'Source.vsp3').write_bytes(xml.encode('utf-8'))
                (folder / 'Prepare.vspscript').write_bytes(script.encode('utf-8'))
                with (folder / 'run.log').open('wb') as log:
                    try:
                        run = subprocess.run([self.executable, '-script', 'Prepare.vspscript'], cwd=folder,
                                             stdout=log, stderr=subprocess.STDOUT, timeout=180,
                                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    except subprocess.TimeoutExpired as exc:
                        raise ValueError('OpenVSP не завершил подготовку за 180 секунд. Модель не изменена.') from exc
                    except OSError as exc:
                        raise ValueError('Не удалось запустить vspscript. Проверь путь и комплект DLL OpenVSP.') from exc
                with (folder / 'run.log').open('rb') as log:
                    message = log.read(12000).decode('utf-8', errors='replace')
                file = folder / output
                if 'SECTION_STUDIO_ERROR' in message or f'SECTION_STUDIO_SAVED: {output}' not in message or run.returncode != 0 or not file.is_file():
                    raise ValueError('OpenVSP не подготовил модель.\n' + (message[-6000:] or f'Код завершения: {run.returncode}'))
                if file.stat().st_size > MAX_INPUT:
                    raise ValueError('Результат подготовки превышает 64 МБ.')
                content = file.read_text(encoding='utf-8')
                if kind == 'sections':
                    return {'ok': True, 'xml': merge_selected(xml, content, chosen)}
                return {'ok': True, 'wingData': json.loads(content)}
        finally:
            self.busy.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def allowed(self, api=False):
        if self.headers.get('Host') != self.server.origin.removeprefix('http://'):
            return False
        origin = self.headers.get('Origin')
        if origin is not None and origin != self.server.origin:
            return False
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return False
        return not api or secrets.compare_digest(self.headers.get('X-Section-Studio', ''), self.server.token)

    def send(self, status, value, mime='application/json; charset=utf-8'):
        payload = json.dumps(value, ensure_ascii=False).encode('utf-8') if isinstance(value, dict) else value
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self.allowed(self.path.startswith('/api/')):
            return self.send(403, {'error': 'Недопустимый запрос.'})
        if self.path in ('/', '/Section_Studio.html'):
            html = (ROOT / 'Section_Studio.html').read_text(encoding='utf-8')
            config = json.dumps({'token': self.server.token})
            html = html.replace('<head>', '<head><script>window.SectionStudioLocalConfig=' + config + ';</script>', 1)
            return self.send(200, html.encode('utf-8'), 'text/html; charset=utf-8')
        if self.path == '/api/status':
            return self.send(200, {'ok': True, 'executable': self.server.executable, 'busy': self.server.busy.locked(), 'version': '1.0'})
        return self.send(404, {'error': 'Не найдено.'})

    def do_POST(self):
        if not self.allowed(True):
            return self.send(403, {'error': 'Недопустимый запрос.'})
        try:
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('Нужен JSON.')
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= MAX_INPUT:
                raise ValueError('Недопустимый размер запроса.')
            self.connection.settimeout(15)
            data = json.loads(self.rfile.read(size).decode('utf-8'))
            if not isinstance(data, dict):
                raise ValueError('Нужен объект JSON.')
            if self.path == '/api/configure':
                if self.server.busy.locked():
                    raise ValueError('Дождись завершения подготовки.')
                executable = validate_executable(data.get('executable'))
                self.server.config_path.parent.mkdir(parents=True, exist_ok=True)
                # Write settings before reporting success.
                self.server.config_path.write_text(json.dumps({'executable': executable}, ensure_ascii=False), encoding='utf-8')
                self.server.executable = executable
                return self.send(200, {'ok': True, 'executable': executable})
            if self.path == '/api/pick':
                # The user's explicit button opens the native file dialog.
                import tkinter as tk
                from tkinter import filedialog
                window = tk.Tk()
                window.withdraw()
                window.attributes('-topmost', True)
                try:
                    selected = filedialog.askopenfilename(title='Выбери vspscript.exe из OpenVSP', parent=window)
                finally:
                    window.destroy()
                return self.send(200, {'ok': True, 'executable': selected})
            if self.path == '/api/prepare':
                return self.send(200, self.server.prepare(data))
            if self.path == '/api/audit':
                return self.send(200, self.server.audit(data))
            if self.path == '/api/machline-tri':
                text=data.get('tri');units=data.get('units')
                if not isinstance(text,str) or len(text.encode('utf-8'))>40_000_000 or units not in FACTORS:
                    raise ValueError('Нужен ASCII TRI до 40 МБ с заданными единицами.')
                machline_settings(data.get('machline'))
                if not self.server.busy.acquire(blocking=False):
                    raise ValueError('Дождись завершения текущей проверки.')
                try:
                    with tempfile.TemporaryDirectory(prefix='StudioTri_') as folder:
                        path=Path(folder)/'Mesh.tri';path.write_text(text,encoding='utf-8')
                        report=inspect_machline(read_tri(path,FACTORS[units]),data.get('machline'))
                    report.update(externalMesh=True,fileName=str(data.get('fileName','Mesh.tri'))[:160],
                                  openVSPVersion='ASCII TRI',thickSet=-1,thinSet=-1,useMode=False,symmetry=False,preset='external-tri',sourceUnits=units,
                                  sourceHash=hashlib.sha256(text.encode('utf-8')).hexdigest(),excludedComponents=[])
                    report['limits'].insert(0,'Внешняя TRI не сопоставлена текущему VSP3 и не используется для подтверждения ремонта модели.')
                    return self.send(200,{'ok':True,'report':report})
                finally:
                    self.server.busy.release()
            if self.path == '/api/verify-repair':
                return self.send(200, self.server.audit(data, repair=True))
            return self.send(404, {'error': 'Не найдено.'})
        except (ValueError, TypeError, OSError, ImportError, RuntimeError) as exc:
            return self.send(400, {'error': str(exc)})
        except Exception:
            return self.send(500, {'error': 'Подготовка не выполнена. Исходная модель не изменена.'})


def main():
    parser = argparse.ArgumentParser(description='Section Studio 1.0 — local OpenVSP bridge')
    parser.add_argument('--vspscript')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    config_dir = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.config'))) / 'SectionStudio'
    parser.add_argument('--config', default=str(config_dir / 'settings.json'))
    args = parser.parse_args()
    server = Studio(args.config, args.vspscript, args.port)
    print(f'Section Studio 1.0: {server.origin}', flush=True)
    print('Keep this window open. Ctrl+C stops the application.', flush=True)
    if not args.no_browser:
        webbrowser.open(server.origin)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
