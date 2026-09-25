#!/usr/bin/env python3
"""ADB controller for the in-game tools; uses the same command queue as the UI."""
from pathlib import Path
import argparse
import json
import shlex
import subprocess
import time
import uuid
import socket
import shutil

ROOT=Path(__file__).resolve().parents[1]
ADB=ROOT/'tools/sdk/platform-tools/adb'
if not ADB.exists():
    ADB=Path(shutil.which('adb') or str(ADB))
PACKAGE='com.mediocre.smashhit.dev'
PORT=18765

def fast_request(value):
    """adb-forwarded Unix socket, with peer UID checks inside the app."""
    with socket.create_connection(('127.0.0.1',PORT),timeout=2) as connection:
        connection.settimeout(5)
        connection.sendall((value+'\n').encode())
        with connection.makefile('rb') as stream:
            data=stream.readline(2*1024*1024)
            if not data:raise ConnectionError('Developer socket is not ready')
            return json.loads(data)

def forward():
    return adb('forward','tcp:'+str(PORT),'localabstract:smashhit_lab').decode()

def adb(*args,timeout=45):
    if not ADB.is_file():
        raise FileNotFoundError('adb was not found. Install Android platform-tools on PATH or run tools/bootstrap.py.')
    return subprocess.check_output([str(ADB),*map(str,args)],timeout=timeout)

def shell(args,timeout=180):
    # adb shell reparses a command on-device. Preserve JSON using shell quoting
    # for that second parse as well, instead of assuming local argv is enough.
    return adb('shell',shlex.join(list(map(str,args))),timeout=timeout).decode()

def snapshot():
    try:return fast_request('GET')
    except (OSError,ValueError):return json.loads(adb('exec-out','run-as',PACKAGE,'cat','files/shdev/snapshot.json'))

def command(op,wait=True,timeout=90,**kwargs):
    before=snapshot();request_id=uuid.uuid4().hex
    value=dict(op=op,request_id=request_id,**kwargs)
    text=json.dumps(value,separators=(',',':'))
    try:answer=fast_request(text)
    except (OSError,ValueError):answer=shell(['am','broadcast','-a','dev.smashhit.COMMAND','-p',PACKAGE,'--es','command',text])
    if 'queued' not in answer:raise RuntimeError('Command receiver did not accept request: '+str(answer))
    if not wait:return answer
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        state=snapshot()
        if state.get('last_request_id')==request_id or ('last_request_id' not in state and state.get('last_command',0)>before.get('last_command',0)):
            if state.get('request_error',state.get('error')):raise RuntimeError(state.get('request_error',state.get('error')))
            return state
        time.sleep(.25)
    raise TimeoutError('Command not acknowledged: '+op)

def step(count=1,timeout=180):
    state=command('step',count=count);deadline=time.monotonic()+timeout
    while state.get('steps_remaining',0) and time.monotonic()<deadline:
        time.sleep(.3);state=snapshot()
    if state.get('steps_remaining',0):raise TimeoutError('Simulation steps did not finish')
    return state

def capture(name):
    p=ROOT/'artifacts'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(adb('exec-out','screencap','-p',timeout=120));return p

def pull_log(name='lab-events.jsonl'):
    p=ROOT/'experiments'/name
    # Stop/pause the app first when a perfectly stable capture is required.
    # Read oldest to newest; old addon versions may have no rotated archives.
    with p.open('wb') as output:
        for suffix in ['.2','.1','']:
            try:data=adb('exec-out','run-as',PACKAGE,'cat','files/shdev/events.jsonl'+suffix,timeout=60)
            except subprocess.CalledProcessError:
                if not suffix:raise
                continue
            output.write(data)
    return p

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['snapshot','command','step','screen','log','forward']);parser.add_argument('value',nargs='?');args=parser.parse_args()
    if args.operation=='snapshot':print(json.dumps(snapshot(),indent=2))
    elif args.operation=='command':print(json.dumps(command(**json.loads(args.value)),indent=2))
    elif args.operation=='step':print(json.dumps(step(int(args.value or '1')),indent=2))
    elif args.operation=='screen':print(capture(args.value or 'lab.png'))
    elif args.operation=='log':print(pull_log(args.value or 'lab-events.jsonl'))
    elif args.operation=='forward':print(forward())
