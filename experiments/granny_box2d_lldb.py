"""Run inside NDK LLDB after its version-checked host connects to Granny Smith.

One temporary breakpoint observes the original Box2D call, then is removed.
The process is detached and resumed in finally, including failed observations.
"""
import json
import math
import os
from pathlib import Path
import struct
import time

import lldb

target = lldb.debugger.GetSelectedTarget()
process = target.GetProcess()
report = {'pid': process.GetProcessID(), 'errors': [], 'registers': None}
breakpoint = None
started = time.monotonic()
try:
    if process.GetProcessID() != int(os.environ['GRANNY_LLDB_PID']):
        raise RuntimeError('Debugger attached to the wrong process')
    address = int(os.environ['GRANNY_LLDB_BREAKPOINT'], 16)
    breakpoint = target.BreakpointCreateByAddress(address)
    if not breakpoint.IsValid() or breakpoint.GetNumLocations() != 1:
        raise RuntimeError('Breakpoint did not resolve')
    lldb.debugger.SetAsync(True)
    initial_stop_id = process.GetStopID()
    error = process.Continue()
    if error.Fail():
        raise RuntimeError(str(error))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = process.GetState()
        if state == lldb.eStateStopped and process.GetStopID() != initial_stop_id:
            hit = None
            for thread in process:
                if thread.GetStopReason() == lldb.eStopReasonBreakpoint and thread.GetStopReasonDataAtIndex(0) == breakpoint.GetID():
                    hit = thread
                    break
            if hit is None:
                raise RuntimeError('Unexpected debugger stop: ' + process.GetSelectedThread().GetStopDescription(256))
            frame = hit.GetFrameAtIndex(0)
            regs = {name: frame.FindRegister(name).GetValueAsUnsigned() for name in ('r0', 'r1', 'r2', 'r3', 'pc', 'lr')}
            report.update(thread=hit.GetThreadID(), breakpoint_address=hex(address), registers=regs,
                          dt=struct.unpack('<f', struct.pack('<I', regs['r1']))[0],
                          velocity_iterations=regs['r2'], position_iterations=regs['r3'])
            break
        if state in (lldb.eStateExited, lldb.eStateDetached, lldb.eStateCrashed, lldb.eStateInvalid):
            raise RuntimeError('Process left the running state: ' + str(state))
        time.sleep(.1)
    else:
        raise TimeoutError('Box2D breakpoint was not reached in 60 seconds')
except Exception as error:
    report['errors'].append(str(error))
finally:
    if breakpoint is not None:
        target.BreakpointDelete(breakpoint.GetID())
    error = process.Detach(False)
    report['detached_and_resumed'] = error.Success()
    if error.Fail():
        report['errors'].append('Detach: ' + str(error))
report['elapsed_seconds'] = time.monotonic() - started
report['status'] = ('OBSERVED' if not report['errors'] and report['registers'] and
                    report['velocity_iterations'] == 5 and report['position_iterations'] == 2 and
                    math.isfinite(report['dt']) and 0 < report['dt'] <= 1 else 'INCOMPLETE')
Path(os.environ['GRANNY_LLDB_RESULT']).write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
