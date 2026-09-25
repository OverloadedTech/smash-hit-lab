"""Read a process interval from the append-only native laboratory event log."""

import json
from pathlib import Path


def process_events(path: Path, wanted_pid: int):
    """Reject corrupt evidence within the requested process; report other gaps.

    Ordinary records inherit the PID from instrumentation_installed. A prior
    emulator interruption can leave a damaged line in an older process block;
    that must not be silently interpreted as evidence from the current run.
    """
    events = []
    outside_errors = []
    current_pid = None
    offset = 0
    with path.open("rb") as source:
        for number, raw in enumerate(source, 1):
            try:
                event = json.loads(raw)
            except (ValueError, UnicodeError) as error:
                detail = dict(
                    line=number, offset=offset, bytes=len(raw), pid=current_pid
                )
                if current_pid == wanted_pid:
                    raise ValueError(
                        f"Damaged event in requested process: {detail}"
                    ) from error
                outside_errors.append(detail)
            else:
                if event.get("event") == "instrumentation_installed":
                    current_pid = event["pid"]
                if current_pid == wanted_pid:
                    events.append(event)
            offset += len(raw)
    if not events:
        raise ValueError(f"No instrumentation interval for PID {wanted_pid}")
    return events, outside_errors
