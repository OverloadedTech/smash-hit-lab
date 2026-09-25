#!/usr/bin/env python3
"""Summarize recorded native events without inventing unobserved state.

Usage: python3 experiments/analyze_events.py experiments/native-events.jsonl
Results are restricted to the PID/hash and time intervals in controlled results.
"""
from collections import Counter
import csv
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments/controlled"


def world(local, origin):
    if local is None:
        return None
    return [local[0], local[1], local[2] + origin]


def main():
    device = json.loads((ROOT / "experiments/device.json").read_text())
    results = [json.loads(p.read_text()) for p in sorted(OUT.glob("result_*.json"))]
    assert results, "No controlled experiment results"
    assert all(r["native_pid"] == device["native_pid"] and
               r["apk_sha256"] == device["apk_sha256"] for r in results)
    intervals = {r["phase"]: (r["native_start_time"], r["native_end_time"])
                 for r in results}
    events = []
    pid = None
    with Path(sys.argv[1]).open() as source:
        for line_number, line in enumerate(source, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid event on line {line_number}") from error
            if "pid" in event:
                pid = event["pid"]
            if pid == device["native_pid"]:
                events.append(event)
    assert events, "No events from the verified runtime PID"

    batch_rooms = {}
    room_info = {}
    for event in events:
        candidates = [event.get("room"), event.get("current"), event.get("next")]
        sample = event.get("snapshot", {})
        candidates += [sample.get("current_room"), sample.get("next_room")]
        for room in candidates:
            if not isinstance(room, dict):
                continue
            room_info[room["id"]] = room
            for batch in room.get("batches", []):
                batch_rooms[batch["id"]] = room["id"]

    summary = dict(apk_sha256=device["apk_sha256"], native_pid=device["native_pid"],
                   runtime=device["runtime"], phases={})
    selected = []
    rows = []
    for result in results:
        phase = result["phase"]
        begin, end = intervals[phase]
        subset = [e for e in events if begin <= e["time"] <= end]
        assert subset, f"No events in {phase} interval"
        counts = Counter(e["event"] for e in subset)
        loads = [e for e in subset if e["event"] == "batch_load"]
        groups = Counter((e["frame"], batch_rooms.get(e["batch"]["id"])) for e in loads)
        destroys = [e for e in subset if e["event"] == "room_destroy_begin"]
        destroyed_ids = {e["id"] for e in subset if e["event"] == "room_destroy_end"}
        samples = [e["snapshot"] for e in subset if e["event"] == "sample"]
        rss = [s["memory"]["VmRSS_KiB"] for s in samples
               if "VmRSS_KiB" in s.get("memory", {})]
        detail = dict(result=result["result"], native_seconds=end-begin,
                      events=dict(counts),
                      batch_load_threads=sorted({e["thread"] for e in loads}),
                      max_batch_loads_per_room_per_frame=max(groups.values(), default=0),
                      batch_load_ms_median=statistics.median(e["duration_ms"] for e in loads)
                        if loads else None,
                      batch_load_ms_max=max((e["duration_ms"] for e in loads), default=None),
                      room_destructors=[dict(id=e["room"]["id"], index=e["room"]["index"],
                                             name=e["room"]["name"], frame=e["frame"],
                                             update=e["update"], completed=e["room"]["id"] in destroyed_ids,
                                             retained_batches=len(e["room"].get("batches", [])),
                                             static_shapes=e["room"]["static_shapes"])
                                        for e in destroys],
                      rss_KiB_range=[min(rss), max(rss)] if rss else None)
        summary["phases"][phase] = detail
        for event in subset:
            selected.append(dict(experiment=phase, **event))
            row = dict(experiment=phase, event=event["event"], time=event["time"],
                       frame=event["frame"], update=event["update"])
            origin = event.get("origin_z", 0)
            p = world(event.get("player_local"), origin)
            c = world(event.get("camera_local"), origin)
            for prefix, value in (("player", p), ("camera", c)):
                if value is not None:
                    row.update({prefix + "_" + axis: value[i] for i, axis in enumerate("xyz")})
            if event["event"] == "sample":
                sample = event["snapshot"]
                row.update(entities=sample["entities"], bodies=sample["bodies"],
                           music=sample["music_location"],
                           rss_KiB=sample.get("memory", {}).get("VmRSS_KiB"))
                room = sample.get("current_room")
                row["next_room_index"] = (sample.get("next_room") or {}).get("index")
            else:
                room = event.get("room")
                if not isinstance(room, dict):
                    room = None
            if room:
                row.update(room_id=room["id"], room_index=room["index"], room_name=room["name"],
                           path_distance=room["path_distance"],
                           loaded_batches=sum(b["loaded"] for b in room.get("batches", [])),
                           created_once=room.get("created_once"),
                           live_obstacles=room["live_obstacles"])
            if event["event"] == "batch_load":
                batch = event["batch"]
                room_id = batch_rooms.get(batch["id"])
                row.update(batch_id=batch["id"], batch_path=batch["path"],
                           load_ms=event["duration_ms"], load_thread=event["thread"], room_id=room_id)
                if room_id in room_info:
                    row.update(room_index=room_info[room_id]["index"], room_name=room_info[room_id]["name"])
            if event["event"] == "marker":
                row["marker"] = event["name"]
            rows.append(row)

    (OUT / "event_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (OUT / "events.jsonl").open("w") as target:
        for event in sorted(selected, key=lambda e: e["time"]):
            target.write(json.dumps(event, separators=(",", ":")) + "\n")
    fields = ["experiment", "event", "time", "frame", "update", "player_x", "player_y", "player_z",
              "camera_x", "camera_y", "camera_z", "room_id", "room_index", "room_name",
              "next_room_index", "path_distance", "loaded_batches", "created_once", "live_obstacles",
              "entities", "bodies", "music", "rss_KiB", "batch_id", "batch_path", "load_ms", "load_thread", "marker"]
    with (OUT / "timeline.csv").open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda e: e["time"]))
    print(json.dumps({p: {k: v for k, v in s.items() if k != "room_destructors"}
                      for p, s in summary["phases"].items()}, indent=2))


if __name__ == "__main__":
    main()
