#!/usr/bin/env python3
"""Second-phase device experiments. Evidence is separate from the first release."""

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.lab import command, snapshot, step, adb, forward, shell
from tools.android_input import send as android_input

OUT = ROOT / "experiments/phase2"
OUT.mkdir(exist_ok=True)


def save(name, s=None):
    s = snapshot() if s is None else s
    (OUT / (name + ".json")).write_text(json.dumps(s, indent=2) + "\n")
    print(
        name,
        json.dumps(
            {
                k: s.get(k)
                for k in [
                    "pid",
                    "context",
                    "menu_transition",
                    "player_world",
                    "camera_world",
                    "updates",
                    "game_updates",
                    "player_balls",
                    "immortal",
                    "player_flight",
                ]
            }
        ),
        flush=True,
    )
    return s


def batch(*commands):
    return command("batch", commands=list(commands))


def wait_for(predicate, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = snapshot()
        if predicate(s):
            return s
        time.sleep(0.3)
    raise TimeoutError("Native state condition did not become true")


def settled():
    return wait_for(
        lambda s: all(
            b["loaded"]
            for r in [s.get("current_room"), s.get("next_room")]
            if r
            for b in r["batches"]
        )
    )


def screen(name):
    (OUT / (name + ".png")).write_bytes(adb("exec-out", "screencap", "-p", timeout=120))


def near(a, b, eps=0.003):
    return max(abs(x - y) for x, y in zip(a, b)) < eps


def reset():
    if not snapshot().get("enabled"):
        command("enable", value=True)
    if not snapshot().get("playing"):
        command("transition", target="game", capture=False)
        wait_for(lambda s: s["context"] == "game")
    batch(
        {"op": "mode", "value": "inspect"},
        {"op": "immortal", "value": False},
        {"op": "unlimited_balls", "value": False},
        {"op": "cruise", "value": False},
        {"op": "reload_level", "from_start": True},
        {"op": "no_fog", "value": True},
        {"op": "two_sided", "value": True},
        {"op": "teleport", "target": "camera", "position": [0, 1, 0]},
        {"op": "look", "rotation_degrees": [0, 0, 0]},
    )
    step(1)
    s = settled()
    assert (
        s["current_room"]["name"] == "basic/basic" and s["current_room"]["index"] == 0
    ), s["current_room"]
    return s


def menu():
    s = snapshot()
    if s.get("playing"):
        command("transition", target="menu", capture=False)
        wait_for(lambda s: s["context"] == "menu")
    # Native state 1 includes the startup logo. Advance its actual Scene ticks
    # before claiming we have inspected the main menu itself.
    step(360)
    base = save("menu_00_original", command("mode", value="inspect"))
    screen("menu_00_original")
    assert base["context"] == "menu" and not base["world_running"]
    assert (
        base["native_tick"] >= 150 and base["native_loaded"]
    ), "Still in startup animation"
    before = base["game_updates"]
    p = base["camera_world"]
    fly = save(
        "menu_01_outside",
        batch(
            {
                "op": "teleport",
                "target": "camera",
                "position": [p[0] + 12, p[1] + 8, p[2] - 10],
            },
            {"op": "look", "rotation_degrees": [-20, 180, 10]},
        ),
    )
    screen("menu_01_outside")
    assert (
        near(base["player_world"], fly["player_world"])
        and fly["game_updates"] == before
    )
    assert (
        base["native_tick"] == fly["native_tick"]
    ), "Native startup counter changed during freeze"
    assert not near(p, fly["camera_world"])
    command("transition", target="game", capture=True)
    half = save(
        "menu_02_halfway_to_game",
        wait_for(
            lambda s: not s["transition_capture_pending"]
            and s["frozen"]
            and s["playing"]
        ),
    )
    assert 0.35 < half["menu_transition"] < 0.65, half["menu_transition"]
    assert (
        half["current_room"]["name"] == "basic/basic"
        and len(half["current_room"]["batches"]) > 0
    )
    time.sleep(3)
    still = save("menu_03_halfway_still")
    assert (
        still["game_updates"] == half["game_updates"]
        and still["menu_transition"] == half["menu_transition"]
    )
    screen("menu_03_halfway_still")
    command("mode", value="follow")
    save("menu_04_game", wait_for(lambda s: s["context"] == "game"))
    command("mode", value="inspect")
    command("transition", target="menu", capture=True)
    back = save(
        "menu_05_halfway_to_menu",
        wait_for(lambda s: not s["transition_capture_pending"] and s["frozen"]),
    )
    assert 0.35 < back["menu_transition"] < 0.65 and not back["playing"]
    original = back["camera_world"]
    updates = back["game_updates"]
    command("speed", value=10)
    command("move", value=[0, 1, 0])
    time.sleep(1.5)
    moved = save("menu_06_fly_transition", command("move", value=[0, 0, 0]))
    screen("menu_06_fly_transition")
    assert (
        moved["camera_world"][1] > original[1] + 1 and moved["game_updates"] == updates
    )
    command("mode", value="follow")
    save("menu_07_menu", wait_for(lambda s: s["context"] == "menu"))
    command("mode", value="inspect")


def flight():
    reset()
    command("mode", value="player")
    base = save(
        "flight_00",
        batch(
            {"op": "speed", "value": 25},
            {"op": "look", "rotation_degrees": [0, 0, 0]},
            {"op": "teleport", "target": "player", "position": [30, 20, -10]},
        ),
    )
    assert base["player_flight"] and base["world_running"] and base["noclip"]
    assert near(base["player_world"], base["camera_world"])
    command("move", value=[1, 1, 0])
    time.sleep(2)
    side = save("flight_01_sideways_up", command("move", value=[0, 0, 0]))
    assert (
        side["player_world"][0] > base["player_world"][0] + 1
        and side["player_world"][1] > base["player_world"][1] + 1
    )
    assert (
        near(side["player_world"], side["camera_world"])
        and side["updates"] > base["updates"]
    )
    command("move", value=[-1, -1, 0])
    time.sleep(1)
    reverse = save("flight_02_left_down", command("move", value=[0, 0, 0]))
    assert (
        reverse["player_world"][0] < side["player_world"][0] - 1
        and reverse["player_world"][1] < side["player_world"][1] - 1
    )
    command("cruise", value=True)
    forward = save(
        "flight_03_cruise", wait_for(lambda s: s["current_room"]["index"] >= 1)
    )
    assert forward["player_world"][2] < -160 and not forward["game_over"]
    command("cruise", value=False)
    command("look", rotation_degrees=[0, 180, 0])
    command("move", value=[0, 0, 1])
    time.sleep(1)
    backward = save("flight_04_backward", command("move", value=[0, 0, 0]))
    assert backward["player_world"][2] > forward["player_world"][2] + 1
    paused = save("flight_05_paused", command("freeze", value=True))
    command("move", value=[0, 1, 0])
    time.sleep(1)
    held = save("flight_06_controls_paused", command("move", value=[0, 0, 0]))
    assert (
        near(paused["player_world"], held["player_world"])
        and paused["updates"] == held["updates"]
    )
    detached = save("flight_07_inspect", command("mode", value="inspect"))
    command("move", value=[0, 1, 0])
    time.sleep(1)
    camera = save("flight_08_camera_only", command("move", value=[0, 0, 0]))
    assert (
        near(detached["player_world"], camera["player_world"])
        and camera["camera_world"][1] > detached["camera_world"][1] + 1
    )
    screen("flight_08_camera_only")


def immortality():
    base = save("immortal_00_baseline", reset())
    assert base["player_balls"] == 25
    damage = save("immortal_01_native_damage", command("probe_damage"))
    assert damage["player_balls"] == 15
    command("immortal", value=True)
    ignored = save("immortal_02_damage_ignored", command("probe_damage"))
    assert (
        ignored["player_balls"] == 15
        and ignored["ignored_hits"] > damage["ignored_hits"]
    )
    command("immortal", value=False)
    damage = save("immortal_03_damage_restored", command("probe_damage"))
    assert damage["player_balls"] == 5
    empty = save("immortal_04_empty_probe", command("probe_damage"))
    assert empty["player_balls"] == 0
    one = save("immortal_05_last_ball", command("immortal", value=True))
    assert one["player_balls"] == 1
    normal = save("immortal_06_normal_mode", command("mode", value="play"))
    assert normal["immortal"] and not normal["enabled"]
    ids = {b["id"] for b in normal["balls_in_world"]}
    time.sleep(2)
    android_input("tap", x=480, y=410, duration_ms=250)
    after = save(
        "immortal_07_shot_last_ball",
        wait_for(lambda s: any(b["id"] not in ids for b in s["balls_in_world"])),
    )
    assert (
        after["player_balls"] == 1 and not after["game_over"] and not after["enabled"]
    )
    # The emulator's screenshot can take long enough for normal progression to
    # reach a tutorial pause. Reset between shot cases so that scripted native
    # tutorial input does not masquerade as a failed shooting feature.
    command("mode", value="inspect")
    reset()
    command("immortal", value=True)
    command("unlimited_balls", value=True)
    command("mode", value="play")
    time.sleep(2.5)  # Let the Android overlay poll and release normal touch input.
    unlimited = save("immortal_08_unlimited")
    balls = unlimited["player_balls"]
    ids = {b["id"] for b in unlimited["balls_in_world"]}
    android_input("tap", x=520, y=390, duration_ms=250)
    after = save(
        "immortal_09_unlimited_shot",
        wait_for(lambda s: any(b["id"] not in ids for b in s["balls_in_world"])),
    )
    assert after["player_balls"] == balls
    command("mode", value="inspect")
    screen("immortal_09_verified")
    command("immortal", value=False)
    command("unlimited_balls", value=False)


def editor():
    reset()
    import experiments.run_experiments as old

    old.OUT = OUT / "editor_regression"
    old.OUT.mkdir(exist_ok=True)
    old.reset = reset
    old.capture = lambda name: screen("editor_regression_" + Path(name).stem)
    old.phase_editor()


def streaming_regression():
    import experiments.run_experiments as old

    old.OUT = OUT / "streaming_regression"
    old.OUT.mkdir(exist_ok=True)
    old.reset = reset
    old.capture = lambda name: screen("streaming_regression_" + Path(name).stem)
    old.phase_boundary()
    old.phase_camera_streaming()
    old.phase_noclip()


def balls():
    reset()
    # Move the real normal pose above/outside the corridor so the shot has no
    # floor beneath it. Native rail movement controls Z; X/Y remain observable.
    command("teleport", target="player", position=[30, 15, -5])
    command("mode", value="play")
    time.sleep(2.5)
    # An actual touch creates the projectile; no synthetic body or replacement
    # physics is used. Hold the player only after that shot has been observed.
    before = snapshot()
    known = {b["id"] for b in before["balls_in_world"]}
    android_input("tap", x=520, y=400, duration_ms=250)
    shot = save(
        "ball_00_shot",
        wait_for(lambda s: any(b["id"] not in known for b in s["balls_in_world"])),
    )
    assert shot["player_world"][0] > 20 and shot["player_world"][1] > 10
    shot_ids = {b["id"] for b in shot["balls_in_world"] if b["id"] not in known}
    command("mode", value="inspect")
    command("progression_hold", value=True)
    base = save("ball_01_held_player")
    inactive = None
    for index in range(30):
        s = save("ball_02_step_%02d" % index, step(60))
        assert near(s["player_world"], base["player_world"])
        candidates = [
            b
            for b in s["balls_in_world"]
            if b["id"] in shot_ids and not b["active"] and b["position"][1] < -9
        ]
        if candidates:
            inactive = candidates[0]
            break
    assert (
        inactive
    ), "The observed shot did not produce an inactive fallen ball in the allotted updates"
    still = save("ball_03_inactive_retained", step(60))
    retained = next(b for b in still["balls_in_world"] if b["id"] == inactive["id"])
    assert near(retained["position"], inactive["position"]) and not retained["active"]
    command("teleport", target="player", position=[0, 1, inactive["position"][2] - 5])
    destroyed = save("ball_04_passed_by_player", step(1))
    assert all(b["id"] != inactive["id"] for b in destroyed["balls_in_world"])
    (OUT / "ball_lifecycle_summary.json").write_text(
        json.dumps(
            {
                "inactive_body": inactive,
                "retained_after_60_more_updates": retained,
                "destroyed_after_player_z": destroyed["player_world"][2],
            },
            indent=2,
        )
        + "\n"
    )


def resume():
    from tools.read_save import decode
    from tools.lab import fast_request
    from tools.event_log import process_events

    def disk(label):
        data = adb(
            "exec-out",
            "run-as",
            "com.mediocre.smashhit.dev",
            "cat",
            "files/quicksave.dat",
        )
        (OUT / (label + ".dat")).write_bytes(data)
        root = decode(data, ROOT / "com.smash.hit.apk")
        result = {
            "root": root.tag,
            "attributes": root.attrib,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        (OUT / (label + ".json")).write_text(json.dumps(result, indent=2) + "\n")
        return result

    reset()
    command("teleport", target="player", position=[0, 1, -200])
    step(5)
    settled()
    entered = save("resume_00_entered_room")
    assert entered["current_room"]["index"] == 1
    automatic = disk("resume_01_automatic_save")
    assert automatic["attributes"]["room"] == "1", automatic
    # Change state after the automatic room-entry save, including a source box.
    batch(
        {"op": "teleport", "target": "player", "position": [13, 8, -230]},
        {"op": "teleport", "target": "camera", "position": [0, 1, -205]},
    )
    step(1)
    s = snapshot()
    first = s["current_room"]["batches"][0]
    source = first["path"].removeprefix("segments/").removesuffix(".mesh")
    mapping = json.loads(
        (ROOT / "dev/assets/shdev/geometry" / (source + ".json")).read_text()
    )
    box = next(b for b in mapping["boxes"] if b["editable"])
    original = command("select", id=first["id"], box=box["ordinal"])["selection"]
    pos = original["position"].copy()
    pos[0] += 25
    pos[1] += 12
    command("transform", position=pos, rotation_degrees=[0, 25, 0], scale=[1.2, 1, 1])
    command("probe_damage")
    before = save("resume_02_before_home")
    pid = before["pid"]
    android_input("key", code=3, duration_ms=120)
    time.sleep(2)
    background = save("resume_03_background")
    shell(
        [
            "am",
            "start",
            "-n",
            "com.mediocre.smashhit.dev/com.mediocre.smashhit.MainActivity",
        ]
    )
    warm = save(
        "resume_04_warm",
        wait_for(lambda s: s["pid"] == pid and s["frame"] > background["frame"]),
    )
    assert (
        near(warm["player_world"], before["player_world"])
        and warm["current_room"]["id"] == before["current_room"]["id"]
    )
    assert (
        warm["selection"]["mesh_position_checksum"]
        == before["selection"]["mesh_position_checksum"]
    )
    assert warm["player_balls"] == before["player_balls"]
    saved = disk("resume_05_disk_before_cold")
    # Preserve the complete old process log before a real process death.
    print(
        adb(
            "pull",
            "/data/data/com.mediocre.smashhit.dev/files/shdev/events.jsonl",
            OUT / "native-events-before-cold.jsonl",
            timeout=300,
        ).decode(),
        flush=True,
    )
    shell(["am", "force-stop", "com.mediocre.smashhit.dev"])
    shell(
        [
            "am",
            "start",
            "-n",
            "com.mediocre.smashhit.dev/com.mediocre.smashhit.MainActivity",
        ]
    )
    forward()
    deadline = time.monotonic() + 300
    cold = None
    while time.monotonic() < deadline:
        try:
            candidate = fast_request("GET")
            if (
                candidate.get("pid") != pid
                and candidate.get("native_loaded")
                and candidate.get("playing")
                and candidate.get("current_room")
            ):
                cold = candidate
                break
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    assert cold, "A fresh native process did not restore the quick-save"
    save("resume_06_cold_before_tools", cold)
    cold = save("resume_07_cold_inspect", command("mode", value="inspect"))
    # Record the actual new process before further assertions. A failed check
    # must not leave the next experiment believing the dead PID is still live.
    device = json.loads((OUT / "device.json").read_text())
    device["native_pid"] = cold["pid"]
    installed = shell(["pm", "path", device["package"]]).split("package:")[1].strip()
    assert shell(["sha256sum", installed]).split()[0] == device["apk_sha256"]
    (OUT / "device.json").write_text(json.dumps(device, indent=2) + "\n")
    assert cold["pid"] != pid and cold["quick_loaded"]
    assert cold["current_room"]["index"] == int(saved["attributes"]["room"])
    assert cold["player_balls"] == int(saved["attributes"]["balls"])
    # quickLoad restores score, but Level::reset reconstructs displayed path
    # distance at the room entrance. Level::update then copies that distance to
    # Player::score. Check both stages instead of assuming score is immutable.
    post_log = OUT / "native-events-after-cold.jsonl"
    adb(
        "pull",
        "/data/data/com.mediocre.smashhit.dev/files/shdev/events.jsonl",
        post_log,
        timeout=300,
    )
    cold_events, earlier_log_gaps = process_events(post_log, cold["pid"])
    restored_event = next(
        event
        for event in cold_events
        if event.get("event") == "quick_load" and event.get("restored")
    )
    assert restored_event["score"] == int(saved["attributes"]["score"])
    assert restored_event["balls"] == int(saved["attributes"]["balls"])
    assert cold["player_score"] == int(cold["display_distance"])
    assert cold["player_score"] < int(saved["attributes"]["score"])
    assert not near(cold["player_world"][:2], before["player_world"][:2])
    assert abs(cold["current_room"]["path_distance"]) < 5, cold["current_room"][
        "path_distance"
    ]
    restored_batch = next(
        (
            b
            for b in cold["current_room"]["batches"]
            if b["path"] == first["path"] and b["offset"] == first["offset"]
        ),
        None,
    )
    geometry_result = "The generated room selected a different segment at that location"
    if restored_batch:
        settled()
        restored = save(
            "resume_08_geometry_rebuilt",
            command("select", id=restored_batch["id"], box=box["ordinal"]),
        )["selection"]
        assert restored["mesh_position_checksum"] == original["mesh_position_checksum"]
        assert (
            restored["mesh_position_checksum"]
            != before["selection"]["mesh_position_checksum"]
        )
        geometry_result = (
            "Matching segment reconstructed with original geometry; runtime edit absent"
        )
    summary = {
        "warm_pid": pid,
        "cold_pid": cold["pid"],
        "warm_position": warm["player_world"],
        "cold_position": cold["player_world"],
        "warm_room_distance": warm["current_room"]["path_distance"],
        "cold_room_distance": cold["current_room"]["path_distance"],
        "saved_attributes": saved["attributes"],
        "warm_balls": warm["player_balls"],
        "cold_balls": cold["player_balls"],
        "quick_load_event": restored_event,
        "log_gaps_outside_cold_process": earlier_log_gaps,
        "score_after_level_rebuild": cold["player_score"],
        "display_distance_after_level_rebuild": cold["display_distance"],
        "geometry": geometry_result,
        "method": "Developer freeze held state during Home/reopen; then am force-stop caused actual process death. No save file was edited.",
    }
    (OUT / "resume_summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def run(phase):
    device = json.loads((OUT / "device.json").read_text())
    h = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report = dict(
        phase=phase,
        start_utc=datetime.now(timezone.utc).isoformat(),
        **device,
        harness_sha256=h,
    )
    (OUT / "harnesses").mkdir(exist_ok=True)
    (OUT / "harnesses" / (h + ".py")).write_bytes(Path(__file__).read_bytes())
    assert snapshot()["pid"] == device["native_pid"]
    command("enable", value=True)
    command("marker", name="phase2_begin_" + phase)
    try:
        globals()[phase]()
        report["result"] = "PASS"
    except Exception as e:
        report["result"] = "FAIL"
        report["error"] = repr(e)
        save("failure_" + phase)
        raise
    finally:
        if not snapshot()["enabled"]:
            command("enable", value=True)
        command("marker", name="phase2_end_" + phase + "_" + report["result"])
        report["end_utc"] = datetime.now(timezone.utc).isoformat()
        (OUT / ("result_" + phase + ".json")).write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    run(sys.argv[1])
