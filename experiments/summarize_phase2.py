#!/usr/bin/env python3
"""Index expanded-release evidence and reject mismatched or incomplete results."""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments/phase2"


def read(path):
    return json.loads(path.read_text())


def main():
    build = read(ROOT / "artifacts/build-report.json")
    apk_hash = hashlib.sha256((ROOT / build["apk"]).read_bytes()).hexdigest()
    assert apk_hash == build["sha256"]
    raw_log = OUT / "native-events-final.jsonl"
    records, gaps = [], []
    pid, offset = None, 0
    for line, raw in enumerate(raw_log.open("rb"), 1):
        try:
            event = json.loads(raw)
        except (ValueError, UnicodeError):
            gaps.append(dict(line=line, offset=offset, bytes=len(raw), native_pid=pid))
        else:
            if event.get("event") == "instrumentation_installed":
                pid = event["pid"]
            records.append(dict(native_pid=pid, log_line=line, **event))
        offset += len(raw)
    checks = []
    verified_events = []
    for phase in [
        "menu",
        "flight",
        "immortality",
        "balls",
        "editor",
        "resume",
        "streaming_regression",
    ]:
        result_file = OUT / ("result_" + phase + ".json")
        result = read(result_file)
        assert result["result"] == "PASS" and result["apk_sha256"] == apk_hash, phase
        harness = OUT / "harnesses" / (result["harness_sha256"] + ".py")
        assert (
            hashlib.sha256(harness.read_bytes()).hexdigest() == result["harness_sha256"]
        )
        begin = next(
            i
            for i, event in enumerate(records)
            if event.get("event") == "marker"
            and event.get("name") == "phase2_begin_" + phase
            and event["native_pid"] == result["native_pid"]
        )
        end = next(
            i
            for i in range(begin + 1, len(records))
            if records[i].get("event") == "marker"
            and records[i].get("name") == "phase2_end_" + phase + "_PASS"
        )
        interval = records[begin : end + 1]
        assert not any(
            interval[0]["log_line"] <= gap["line"] <= interval[-1]["log_line"]
            for gap in gaps
        ), phase
        checks.append(
            dict(
                name=phase,
                category="native runtime",
                result="PASS",
                evidence=str(result_file.relative_to(ROOT)),
                process_ids=sorted({e["native_pid"] for e in interval}),
                log_lines=[interval[0]["log_line"], interval[-1]["log_line"]],
                event_counts=dict(Counter(e["event"] for e in interval)),
            )
        )
        verified_events.extend(dict(experiment=phase, **event) for event in interval)
    for name, path in [
        ("Android UI", OUT / "ui/result.json"),
        ("Desktop to native bridge", ROOT / "experiments/desktop/runtime/result.json"),
    ]:
        result = read(path)
        assert result["result"] == "PASS" and result["apk_sha256"] == apk_hash
        harness = path.parent / "harnesses" / (result["harness_sha256"] + ".py")
        assert (
            hashlib.sha256(harness.read_bytes()).hexdigest() == result["harness_sha256"]
        )
        checks.append(
            dict(
                name=name,
                category="real UI and native runtime",
                result="PASS",
                evidence=str(path.relative_to(ROOT)),
                process_ids=[result["native_pid"]],
            )
        )
    desktop = read(ROOT / "experiments/desktop/result.json")
    assert (
        desktop["result"] == "PASS" and desktop["input_sha256"] == build["input_sha256"]
    )
    harness = (
        ROOT / "experiments/desktop/harnesses" / (desktop["harness_sha256"] + ".py")
    )
    assert hashlib.sha256(harness.read_bytes()).hexdigest() == desktop["harness_sha256"]
    checks.append(
        dict(
            name="Desktop editor and complete catalogue GLB",
            category="real browser and asset comparison",
            result="PASS",
            evidence="experiments/desktop/result.json",
        )
    )
    clean = read(ROOT / "analysis/reports/public-clean-build.json")
    assert clean["input_sha256"] == build["input_sha256"]
    assert clean["unchanged_original_asset_and_library_entries"] == 2433
    checks.append(
        dict(
            name="Clean source build",
            category="build and mapping reproduction",
            result="PASS",
            evidence="analysis/reports/public-clean-build-source.json",
        )
    )
    report = dict(
        result="PASS",
        created_utc=datetime.now(timezone.utc).isoformat(),
        apk_sha256=apk_hash,
        input_sha256=build["input_sha256"],
        checks=checks,
        tested_native_abi="x86_64",
        other_abi_scope="arm64-v8a compiled and statically inspected only",
        event_log_sha256=hashlib.sha256(raw_log.read_bytes()).hexdigest(),
        log_gaps_outside_verified_phase_intervals=gaps,
        limitations="See docs/unknowns.md and docs/phase2_experiments.md; clean rebuild is not a separately runtime-tested APK.",
    )
    (ROOT / "artifacts/phase2-validation-report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    with (OUT / "events-verified.jsonl").open("w") as target:
        for event in verified_events:
            target.write(json.dumps(event, separators=(",", ":")) + "\n")
    print(
        json.dumps(
            dict(
                result="PASS",
                checks=len(checks),
                apk_sha256=apk_hash,
                verified_native_events=len(verified_events),
                log_gaps_outside_intervals=gaps,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
