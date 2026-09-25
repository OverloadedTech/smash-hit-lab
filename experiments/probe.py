#!/usr/bin/env python3
"""Attach probe.js and serve localhost-only commands for repeatable experiments."""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import frida

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--package',default='com.mediocre.smashhit')
parser.add_argument('--port',type=int,default=8765)
parser.add_argument('--pid',type=int)
parser.add_argument('--log',default='experiments/original_probe.jsonl')
args=parser.parse_args()
device=frida.get_usb_device(timeout=20)
pid=args.pid
if pid is None:
    process=next((p for p in device.enumerate_processes() if p.name==args.package),None)
    if process is None:
        raise SystemExit('Start the game before attaching the probe, or provide --pid.')
    pid=process.pid
print(f'Attaching to {pid}',flush=True)
session=device.attach(pid)
script=session.create_script((ROOT/'experiments/probe.js').read_text())
log=(ROOT/args.log).open('a',buffering=1)
lock=threading.Lock()
def on_message(message,data):
    with lock:
        log.write(json.dumps(dict(host_utc=datetime.now(timezone.utc).isoformat(),message=message))+'\n')
    if message.get('type')=='error': print(message,flush=True)
script.on('message',on_message)
script.load()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        try:
            obj=script.exports_sync.snapshot()
            result=json.dumps(obj).encode()
            self.send_response(200)
        except Exception as exc:
            result=json.dumps({'error':str(exc)}).encode();self.send_response(500)
        self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(result)
    def do_POST(self):
        try:
            command=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            result=json.dumps(script.exports_sync.command(command)).encode();self.send_response(200)
        except Exception as exc:
            result=json.dumps({'error':str(exc)}).encode();self.send_response(400)
        self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(result)

print(f'Attached to {pid}; localhost:{args.port}; log {args.log}',flush=True)
try:
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
finally:
    script.unload();session.detach();log.close()
