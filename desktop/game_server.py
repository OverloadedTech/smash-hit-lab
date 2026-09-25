"""Local native-scene editor for PinOut and Granny Smith's embedded Labs.

Run python -m desktop.game_server --game pinout --serial DEVICE_SERIAL.
The source APK stays on the device; exported geometry is private local data.
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import argparse, json, mimetypes, subprocess, threading
from urllib.parse import urlparse
from tools.game_lab import Client

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'desktop/game_web'
PACKAGES = {'pinout': 'com.mediocre.pinout.dev', 'granny-smith': 'com.mediocre.grannysmith.dev'}

class Runtime:
    def __init__(self, game, serial, port):
        self.game, self.package = game, PACKAGES[game]
        self.adb = [str(ROOT / 'tools/sdk/platform-tools/adb')]
        if not Path(self.adb[0]).is_file(): self.adb = ['adb']
        if serial: self.adb += ['-s', serial]
        self.port = port
        self.lock = threading.Lock()
    def device(self, *args):
        return subprocess.run(self.adb + list(args), check=True, capture_output=True, timeout=120).stdout
    def client(self):
        socket_name = 'pinout_lab' if self.game == 'pinout' else 'granny_smith_lab'
        self.device('forward', 'tcp:' + str(self.port), 'localabstract:' + socket_name)
        return Client(self.port, timeout=30)
    def connect(self):
        with self.lock:
            client = self.client()
            snapshot = client.snapshot()
            if snapshot.get('game') != self.game.replace('-', '_'): raise ValueError('The connected Lab is a different game')
            if not snapshot.get('camera_ready'): raise ValueError('Wait for the game scene to finish loading')
            client.command({'op': 'mode', 'value': 'edit', 'expected_pid': snapshot['pid']}, timeout=60)
            result = client.command({'op': 'export_scene', 'expected_pid': snapshot['pid']}, timeout=90)
            data = self.device('exec-out', 'run-as', self.package, 'cat', 'files/mediocre-lab/scene.json')
            scene = json.loads(data)
            if scene.get('format') != 'mediocre-native-scene': raise ValueError('Install the current Lab APK with native scene export')
            if scene['pid'] != result['pid'] or scene['scene_epoch'] != result['scene_epoch']: raise ValueError('Scene changed while exporting; reconnect')
            return scene
    def apply(self, request):
        with self.lock:
            identity = request['identity']
            client = self.client()
            snapshot = client.snapshot()
            if identity.get('game') != snapshot.get('game') or identity.get('library_sha256') != snapshot.get('library_sha256'):
                raise ValueError('The project and connected native game library differ')
            guard = dict(expected_pid=int(identity['pid']), expected_scene_epoch=int(identity['scene_epoch']))
            client.command(dict(op='pause', value=True, **guard), timeout=60)
            state = client.command(dict(op='apply_poses', poses=request['poses'], **guard), timeout=90)
            if request.get('save'): state = client.command(dict(op='save_edits', **guard), timeout=60)
            return state

class Handler(BaseHTTPRequestHandler):
    def trusted(self):
        host = self.headers.get('Host', '')
        return host in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
    def send(self, value, code=200, kind='application/json'):
        if isinstance(value, (dict, list)): value = json.dumps(value, separators=(',', ':')).encode()
        if isinstance(value, str): value = value.encode()
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(value)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers(); self.wfile.write(value)
    def log_message(self, *args): pass
    def do_GET(self):
        if not self.trusted(): return self.send({'error': 'Use the local editor URL'}, 403)
        path = urlparse(self.path).path
        if path == '/api/config': return self.send({'game': self.server.runtime.game})
        base = ROOT / 'desktop/web/vendor' if path.startswith('/vendor/') else WEB
        name = path.removeprefix('/vendor/') if path.startswith('/vendor/') else ('index.html' if path == '/' else path.lstrip('/'))
        file = (base / name).resolve()
        if not file.is_relative_to(base.resolve()) or not file.is_file(): return self.send({'error': 'Not found'}, 404)
        return self.send(file.read_bytes(), kind=mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
    def do_POST(self):
        if not self.trusted() or self.headers.get('Origin', 'http://' + self.headers.get('Host', '')) != 'http://' + self.headers.get('Host', ''):
            return self.send({'error': 'Use the local editor URL'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8_000_000: raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(length))
            if self.path == '/api/connect': return self.send(self.server.runtime.connect())
            if self.path == '/api/apply': return self.send(self.server.runtime.apply(data))
            return self.send({'error': 'Unknown endpoint'}, 404)
        except (ValueError, KeyError, TypeError, OSError, RuntimeError, TimeoutError, subprocess.SubprocessError) as error:
            return self.send({'error': str(error)}, 400)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', choices=PACKAGES, required=True)
    parser.add_argument('--serial')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--device-port', type=int)
    args = parser.parse_args()
    if not (ROOT / 'desktop/web/vendor/three/build/three.module.js').is_file(): raise SystemExit('Run python tools/setup_desktop.py first')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.runtime = Runtime(args.game, args.serial, args.device_port or (18767 if args.game == 'pinout' else 18768))
    print(f'{args.game} native scene editor: http://127.0.0.1:{args.port}', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__ == '__main__': main()
