#!/usr/bin/env python3
"""Verify new presets and cheat switches through real Android UI input."""

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.lab import command, snapshot, adb
from tools.android_input import send
from experiments.phase2_controls import reset, wait_for, near

OUT = ROOT / "experiments/phase2/ui"
OUT.mkdir(exist_ok=True)
actions = []


def save(name, state=None):
    state = snapshot() if state is None else state
    (OUT / (name + ".json")).write_text(json.dumps(state, indent=2) + "\n")
    print(
        name,
        {
            k: state.get(k)
            for k in [
                "pid",
                "enabled",
                "frozen",
                "player_flight",
                "player_world",
                "camera_world",
                "immortal",
                "unlimited_balls",
            ]
        },
        flush=True,
    )
    return state


def hierarchy(name):
    deadline = time.monotonic() + 15
    while True:
        try:
            result = send("hierarchy")
            break
        except RuntimeError as error:
            if (
                "No active accessibility window" not in str(error)
                or time.monotonic() >= deadline
            ):
                raise
            time.sleep(0.5)
    target = OUT / (name + ".xml")
    target.write_text(result["xml"])
    return ET.parse(target).getroot()


def visible_node(root, text):
    for node in root.iter("node"):
        if node.get("text") != text or node.get("visible") == "false":
            continue
        bounds = list(map(int, re.findall(r"\d+", node.get("bounds", ""))))
        if len(bounds) == 4 and bounds[2] > bounds[0] and bounds[3] - bounds[1] > 15:
            return node, bounds
    return None


def tap_text(text, name, scroll=False):
    for attempt in range(5 if scroll else 1):
        root = hierarchy(name + str(attempt))
        found = visible_node(root, text)
        if found:
            node, bounds = found
            x, y = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
            actions.append(dict(text=text, bounds=bounds, checked=node.get("checked")))
            send("tap", x=x, y=y, duration_ms=250)
            time.sleep(1)
            return
        if scroll:
            send("drag", x=815, y=430, to_x=815, to_y=260, duration_ms=700)
            time.sleep(1)
    raise AssertionError("Visible Android control not found: " + text)


def run():
    device = json.loads((ROOT / "experiments/phase2/device.json").read_text())
    report = dict(
        start_utc=datetime.now(timezone.utc).isoformat(),
        **device,
        harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    )
    report["input_helper"] = send("info")
    assert snapshot()["pid"] == device["native_pid"]
    reset()
    command("teleport", target="player", position=[30, 20, -10])
    command("mode", value="play")
    time.sleep(2.5)
    tap_text("DEV", "00_entry")
    wait_for(lambda s: s["enabled"] and s["frozen"])
    tap_text("Explore", "01_tab")
    tap_text("Fly player · world running", "02_player")
    base = save(
        "03_player_mode", wait_for(lambda s: s["player_flight"] and not s["frozen"])
    )
    send("key", code=33, duration_ms=1200)  # E: upward
    moved = save("04_player_moved")
    assert moved["player_world"][1] > base["player_world"][1] + 0.1
    assert near(moved["player_world"], moved["camera_world"])
    tap_text("Pause world", "05_pause")
    frozen = save("06_player_paused", wait_for(lambda s: s["frozen"]))
    send("key", code=33, duration_ms=1200)
    still = save("07_player_still")
    assert near(frozen["player_world"], still["player_world"])
    assert near(frozen["camera_world"], still["camera_world"])
    tap_text("Pause & inspect", "08_inspect")
    before = wait_for(lambda s: s["frozen"] and not s["player_flight"])
    send("key", code=33, duration_ms=1200)
    camera = save("09_camera_only")
    assert near(before["player_world"], camera["player_world"])
    assert camera["camera_world"][1] > before["camera_world"][1] + 0.1
    (OUT / "camera-only-paused.png").write_bytes(
        adb("exec-out", "screencap", "-p", timeout=120)
    )
    tap_text("Immortal · ignore damage, keep last ball", "10_immortal", scroll=True)
    wait_for(lambda s: s["immortal"])
    tap_text("Unlimited balls", "11_unlimited", scroll=True)
    save("12_cheats_enabled", wait_for(lambda s: s["unlimited_balls"]))
    tap_text("Leave tools · normal controls", "13_leave")
    normal = save("14_normal_with_cheats", wait_for(lambda s: not s["enabled"]))
    assert normal["immortal"] and normal["unlimited_balls"]
    time.sleep(2)
    root = hierarchy("15_passive_badge")
    assert any(
        "IMMORTAL" in n.get("text", "") and "UNLIMITED BALLS" in n.get("text", "")
        for n in root.iter("node")
    )
    (OUT / "normal-controls-cheat-badge.png").write_bytes(
        adb("exec-out", "screencap", "-p", timeout=120)
    )
    tap_text("DEV", "16_reopen")
    wait_for(lambda s: s["enabled"])
    tap_text("Immortal · ignore damage, keep last ball", "17_immortal_off", scroll=True)
    wait_for(lambda s: not s["immortal"])
    tap_text("Unlimited balls", "18_unlimited_off", scroll=True)
    final = save("19_cheats_disabled", wait_for(lambda s: not s["unlimited_balls"]))
    assert not final["immortal"]
    reset()
    report.update(
        result="PASS",
        end_utc=datetime.now(timezone.utc).isoformat(),
        actions=actions,
        checks=[
            "DEV/Explore/player preset through visible Android controls",
            "Keyboard movement changes actual out-of-bounds player pose",
            "Pause stops player motion; inspect permits independent camera motion",
            "Cheat switches persist after leaving tools with visible badge",
            "Both cheat switches disable through the UI",
        ],
    )
    save("result", report)


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        save(
            "failure", dict(error=repr(error), actions=actions, native_state=snapshot())
        )
        raise
