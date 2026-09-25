"""Observe one Box2D call through the NDK server's GDB remote protocol.

Run only through verify_granny_box2d.py, which checks the mapped ELF and owns
the debugger server. Avoids LLDB's automatic Android module/symbol discovery.
A temporary software breakpoint is removed before detaching and resuming.
"""
import json
import math
import os
from pathlib import Path
import socket
import struct
import time


class Remote:
    def __init__(self, port):
        self.socket = socket.create_connection(('127.0.0.1', port), timeout=10)
        self.acknowledgments = True
        self.transcript = []

    def byte(self):
        value = self.socket.recv(1)
        if not value:
            raise EOFError('Debugger connection closed')
        return value

    def packet(self, timeout=10):
        self.socket.settimeout(timeout)
        while True:
            marker = self.byte()
            if marker == b'$':
                break
            if marker == b'-':
                raise RuntimeError('Debugger rejected packet checksum')
            if marker != b'+':
                raise RuntimeError('Unexpected packet marker: ' + repr(marker))
        encoded = bytearray()
        while (value := self.byte()) != b'#':
            encoded.extend(value)
            if len(encoded) > 1024 * 1024:
                raise ValueError('Debugger response exceeds 1 MiB')
        checksum = int(self.byte() + self.byte(), 16)
        if sum(encoded) % 256 != checksum:
            raise ValueError('Debugger packet checksum mismatch')
        if self.acknowledgments:
            self.socket.sendall(b'+')
        decoded, index = bytearray(), 0
        while index < len(encoded):
            value = encoded[index]; index += 1
            if value == ord('}'):
                if index == len(encoded):
                    raise ValueError('Truncated packet escape')
                decoded.append(encoded[index] ^ 0x20); index += 1
            elif value == ord('*'):
                if not decoded or index == len(encoded) or encoded[index] < 29:
                    raise ValueError('Invalid packet run length')
                decoded.extend([decoded[-1]] * (encoded[index] - 29)); index += 1
            else:
                decoded.append(value)
        result = decoded.decode('ascii')
        self.transcript.append({'reply': result, 'at': time.monotonic()})
        return result

    def command(self, command, timeout=10):
        self.transcript.append({'command': command, 'at': time.monotonic()})
        data = command.encode('ascii')
        self.socket.sendall(b'$' + data + b'#' + f'{sum(data) % 256:02x}'.encode())
        return self.packet(timeout)

    def okay(self, command):
        result = self.command(command)
        if result != 'OK':
            raise RuntimeError(command + ' returned ' + repr(result))


def fields(response):
    return dict(part.split(':', 1) for part in response.split(';') if ':' in part)


def main():
    started = time.monotonic()
    report = {'pid': int(os.environ['GRANNY_LLDB_PID']), 'errors': [], 'registers': None,
              'method': 'NDK lldb-server, one GDB-remote software breakpoint; no injected agent'}
    remote = None
    breakpoint_set = running = False
    address = int(os.environ['GRANNY_LLDB_BREAKPOINT'], 16)
    try:
        remote = Remote(int(os.environ['GRANNY_LLDB_PORT']))
        report['server_features'] = remote.command('qSupported')
        remote.okay('QStartNoAckMode'); remote.acknowledgments = False
        info = fields(remote.command('qProcessInfo'))
        report['remote_process_info'] = info
        if (int(info.get('pid', '0'), 16) != report['pid'] or
                info.get('endian', 'little') != 'little' or
                os.environ['GRANNY_LLDB_ELF_BYTE_ORDER'] != 'little'):
            raise RuntimeError('Unexpected debugger process or byte order')
        report['byte_order_verified_from_mapped_elf'] = 'little'
        report['remote_host_info'] = fields(remote.command('qHostInfo'))
        stop = remote.command('?')
        report['initial_stop'] = stop
        if stop[:1] not in ('T', 'S'):
            raise RuntimeError('Target is not stopped after attachment')
        initial_thread = fields(stop[3:]).get('thread') if stop.startswith('T') else None
        if initial_thread:
            remote.okay('Hg' + initial_thread)
        required = {'r0', 'r1', 'r2', 'r3', 'pc', 'lr'}
        registers = {}
        for number in range(256):
            response = remote.command(f'qRegisterInfo{number:x}')
            description = fields(response)
            if not description.get('name'):
                raise RuntimeError('Missing register description: ' + repr(response))
            name = description.get('name')
            if name in required:
                if description.get('bitsize') != '32':
                    raise RuntimeError('Unexpected ARM register width')
                registers[name] = number
            if required <= registers.keys():
                break
        else:
            raise RuntimeError('Server did not describe the required ARM registers')
        report['register_numbers'] = registers
        before = remote.command(f'm{address:x},4')
        report['instruction_before_breakpoint'] = before
        if before.lower() != os.environ['GRANNY_LLDB_INSTRUCTION'].lower():
            raise RuntimeError('Runtime instruction differs from the verified ELF')
        remote.okay(f'Z0,{address:x},4'); breakpoint_set = True
        running = True
        stop = remote.command('c', timeout=60)
        running = False
        report['breakpoint_stop'] = stop
        if stop[:1] != 'T':
            raise RuntimeError('Expected a thread stop at the breakpoint: ' + stop)
        thread = fields(stop[3:]).get('thread')
        if not thread:
            raise RuntimeError('Stop packet omitted thread identity')
        remote.okay('Hg' + thread)
        values = {}
        for name, number in registers.items():
            data = bytes.fromhex(remote.command(f'p{number:x}'))
            if len(data) != 4:
                raise RuntimeError('Wrong register response width')
            values[name] = int.from_bytes(data, 'little')
        report.update(thread=thread, breakpoint_address=hex(address), registers=values,
                      dt=struct.unpack('<f', struct.pack('<I', values['r1']))[0],
                      velocity_iterations=values['r2'], position_iterations=values['r3'])
        if values['pc'] != address:
            raise RuntimeError('Process stopped at a different instruction')
    except Exception as error:
        report['errors'].append(str(error))
    finally:
        if remote is not None:
            try:
                if running:
                    remote.socket.sendall(b'\x03')
                    report['interrupt_stop'] = remote.packet(10)
                if breakpoint_set:
                    remote.okay(f'z0,{address:x},4')
                    after = remote.command(f'm{address:x},4')
                    report['instruction_after_breakpoint'] = after
                    if after.lower() != os.environ['GRANNY_LLDB_INSTRUCTION'].lower():
                        raise RuntimeError('Original instruction was not restored')
                    report['breakpoint_removed'] = True
                remote.okay('D')
                report['detached_and_resumed'] = True
            except Exception as error:
                report['errors'].append('Cleanup: ' + str(error))
            finally:
                remote.socket.close()
            report['protocol_transcript'] = [
                {**event, 'elapsed_seconds': event['at'] - started}
                for event in remote.transcript]
            for event in report['protocol_transcript']:
                event.pop('at')
    report['elapsed_seconds'] = time.monotonic() - started
    report['status'] = ('OBSERVED' if not report['errors'] and report['registers'] and
                        report.get('breakpoint_removed') and report.get('detached_and_resumed') and
                        report['velocity_iterations'] == 5 and report['position_iterations'] == 2 and
                        math.isfinite(report['dt']) and 0 < report['dt'] <= 1 else 'INCOMPLETE')
    Path(os.environ['GRANNY_LLDB_RESULT']).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'protocol_transcript'}, indent=2))
    if report['status'] != 'OBSERVED':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
