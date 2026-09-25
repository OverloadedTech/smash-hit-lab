#!/usr/bin/env python3
"""Observe one Granny Smith Box2D step using the bundled NDK debugger.

The original ARMv7 library's mapped bytes and symbol offset are verified first.
This pauses/resumes the original process at one breakpoint; it changes no game
data or save fields. A running Granny Smith research installation is required.
Experimental: the NDK r27c server did not expose ARM registers on the tested
API 23 emulator. Those attempts are INCOMPLETE, not successful observations.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import time

from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_SHA = 'ab1fd12d06952937aa802c3a4e6a4e2c413a20ebfa51a95ca33ca5cd75f788f1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--serial', default='emulator-5556')
    parser.add_argument('--port', type=int, default=27890)
    parser.add_argument('--client', choices=('remote', 'lldb'), default='remote',
                        help='Direct remote protocol avoids automatic Android module discovery')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Port must be between 1024 and 65535')
    args.out = args.out.resolve(); args.out.mkdir(parents=True, exist_ok=False)
    adb = [str(ROOT / 'tools/sdk/platform-tools/adb'), '-s', args.serial]
    ps = subprocess.check_output(adb + ['shell', 'ps'], text=True)
    candidates = [line.split() for line in ps.splitlines() if line.split() and line.split()[-1] == 'com.mediocre.grannysmith']
    if len(candidates) != 1:
        raise SystemExit('Exactly one running original Granny Smith process is required')
    pid = int(candidates[0][1])
    maps = subprocess.check_output(adb + ['shell', 'cat', f'/proc/{pid}/maps'], text=True)
    mapping = next(line.split() for line in maps.splitlines() if line.endswith('/libgrannysmith.so') and int(line.split()[2], 16) == 0)
    library_path = mapping[-1]
    data = subprocess.check_output(adb + ['exec-out', 'cat', library_path])
    if sha(data) != LIBRARY_SHA:
        raise SystemExit('Unsupported mapped ARMv7 library')
    elf = ELFFile(io.BytesIO(data))
    symbol = elf.get_section_by_name('.dynsym').get_symbol_by_name('_ZN7b2World4StepEfii')[0]
    if elf.header['e_machine'] != 'EM_ARM' or elf.elfclass != 32 or not elf.little_endian or symbol['st_value'] & 1:
        raise SystemExit('Expected the verified ARM-mode symbol')
    address = int(mapping[0].split('-')[0], 16) + symbol['st_value']
    segment = next(s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD' and
                   s['p_vaddr'] <= symbol['st_value'] < s['p_vaddr'] + s['p_filesz'])
    instruction_offset = segment['p_offset'] + symbol['st_value'] - segment['p_vaddr']
    instruction = data[instruction_offset:instruction_offset + 4]
    # LLDB 18 requires an actual ELF for `target create`; retain the verified
    # private input alongside the local evidence, outside the source export.
    local_library = args.out / 'mapped-library.so'
    local_library.write_bytes(data)
    toolchain = next((ROOT / 'tools/sdk/ndk').glob('android-ndk-*/toolchains/llvm/prebuilt/linux-x86_64'))
    server = next(toolchain.glob('lib/clang/*/lib/linux/arm/lldb-server'))
    lldb = toolchain / 'bin/lldb'
    probe = ROOT / ('experiments/granny_box2d_remote.py' if args.client == 'remote'
                    else 'experiments/granny_box2d_lldb.py')
    for source in (probe, Path(__file__).resolve()):
        (args.out / source.name).write_bytes(source.read_bytes())
    commands = args.out / 'commands.lldb'
    if args.client == 'lldb':
        commands.write_text('target create --arch arm ' + json.dumps(str(local_library)) + '\n' +
                            f'gdb-remote 127.0.0.1:{args.port}\n' +
                            'script exec(compile(open(' + repr(str(probe)) + ').read(), ' + repr(str(probe)) + ', "exec"))\n')
    report = {'created_utc': datetime.now(timezone.utc).isoformat(), 'serial': args.serial, 'pid': pid,
              'client': args.client,
              'library_path': library_path, 'mapped_library_sha256': LIBRARY_SHA,
              'symbol': symbol.name, 'symbol_offset': hex(symbol['st_value']), 'breakpoint_address': hex(address),
              'sources': {p.name: sha(p.read_bytes()) for p in (probe, Path(__file__).resolve())},
              'server_sha256': sha(server.read_bytes()), 'errors': []}
    environment = os.environ.copy()
    environment.update(GRANNY_LLDB_PID=str(pid), GRANNY_LLDB_PORT=str(args.port),
                       GRANNY_LLDB_ELF_BYTE_ORDER='little',
                       GRANNY_LLDB_INSTRUCTION=instruction.hex(),
                       GRANNY_LLDB_BREAKPOINT=hex(address), GRANNY_LLDB_RESULT=str(args.out / 'observation.json'))
    if args.client == 'lldb':
        environment.update(LD_LIBRARY_PATH=str(toolchain / 'python3/lib') + ':' + str(toolchain / 'lib'),
                           PYTHONHOME=str(toolchain / 'python3'))
    subprocess.run(adb + ['push', str(server), '/data/local/tmp/granny-lldb-server'], check=True, capture_output=True)
    subprocess.run(adb + ['shell', 'chmod', '755', '/data/local/tmp/granny-lldb-server'], check=True)
    subprocess.run(adb + ['forward', f'tcp:{args.port}', f'tcp:{args.port}'], check=True)
    remote_server = '/data/local/tmp/granny-lldb-server'

    def server_pids():
        listing = subprocess.check_output(adb + ['shell', 'ps'], text=True, timeout=10)
        return {int(parts[1]) for line in listing.splitlines()
                if (parts := line.split()) and parts[-1] == remote_server}

    if server_pids():
        raise SystemExit('An existing Granny Smith debugger server is running; finish that session first')

    def process_status():
        result = subprocess.run(adb + ['shell', 'cat', f'/proc/{pid}/status'],
                                capture_output=True, text=True, timeout=10)
        return result.stdout if result.returncode == 0 else None

    with (args.out / 'server.log').open('wb') as server_log, (args.out / 'debugger.log').open('wb') as debugger_log:
        server_process = subprocess.Popen(adb + ['shell', '/data/local/tmp/granny-lldb-server', 'gdbserver',
                                                 f'127.0.0.1:{args.port}', '--attach', str(pid)],
                                          stdout=server_log, stderr=subprocess.STDOUT)
        owned_server_pids = set()
        try:
            # Do not open a trial TCP connection: gdbserver accepts one client.
            # Observe its listen socket on the device before starting LLDB.
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                owned_server_pids.update(server_pids())
                if server_process.poll() is not None:
                    raise RuntimeError('Debugger server exited before accepting a connection')
                sockets = subprocess.check_output(adb + ['shell', 'cat', '/proc/net/tcp', '/proc/net/tcp6'],
                                                  text=True, timeout=10)
                if any(len(parts := line.split()) > 3 and
                       parts[1].endswith(f':{args.port:04X}') and parts[3] == '0A'
                       for line in sockets.splitlines()):
                    break
                time.sleep(.2)
            else:
                raise TimeoutError('Debugger server did not listen within 20 seconds')
            client = ([sys.executable, str(probe)] if args.client == 'remote' else
                      [str(lldb), '--no-lldbinit', '--batch', '--source', str(commands)])
            result = subprocess.run(client,
                                    env=environment, stdout=debugger_log, stderr=subprocess.STDOUT, timeout=150)
            report['debugger_exit_code'] = result.returncode
        except Exception as error:
            report['errors'].append(str(error))
        finally:
            # Normal cleanup is the probe's explicit Detach(False). If LLDB
            # fails before the probe starts, stop only our verified server.
            owned_server_pids.update(server_pids())
            report['debugger_server_pids'] = sorted(owned_server_pids)
            for server_pid in owned_server_pids:
                command = subprocess.run(adb + ['exec-out', 'cat', f'/proc/{server_pid}/cmdline'],
                                         capture_output=True, timeout=10).stdout
                if command.startswith(remote_server.encode() + b'\0gdbserver\0'):
                    subprocess.run(adb + ['shell', 'kill', '-TERM', str(server_pid)],
                                   capture_output=True, timeout=10)
            if server_process.poll() is None:
                server_process.terminate()
            try:
                server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_process.kill(); server_process.wait(timeout=5)
            report['process_status_after_detach'] = process_status()
            status = report['process_status_after_detach'] or ''
            fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
            if fields.get('TracerPid', '').strip() == '0' and fields.get('State', '').strip().startswith(('T', 't')):
                # A server terminated before client attachment may leave its
                # attach SIGSTOP pending. Resume only the original, now
                # untraced package process after checking its identity again.
                command = subprocess.run(adb + ['exec-out', 'cat', f'/proc/{pid}/cmdline'],
                                         capture_output=True, timeout=10).stdout
                if command.split(b'\0')[0] == b'com.mediocre.grannysmith':
                    subprocess.run(adb + ['shell', 'kill', '-CONT', str(pid)],
                                   check=True, capture_output=True, timeout=10)
                    report['cleanup_sigcont'] = True
                    status = process_status() or ''
                    report['process_status_after_detach'] = status
                    fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
            report['process_alive_and_untraced'] = (fields.get('TracerPid', '').strip() == '0' and
                                                    not fields.get('State', '').strip().startswith(('T', 't', 'Z')))
            if not report['process_alive_and_untraced']:
                report['errors'].append('Original process is absent, stopped or still traced after cleanup')
    if (args.out / 'observation.json').exists():
        report['observation'] = json.loads((args.out / 'observation.json').read_text())
    report['status'] = ('OBSERVED' if not report['errors'] and report.get('debugger_exit_code') == 0 and
                        report.get('observation', {}).get('status') == 'OBSERVED'
                        else 'INCOMPLETE')
    (args.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if report['status'] != 'OBSERVED':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
