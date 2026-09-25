#!/usr/bin/env python3
"""Drive desktop controls, then verify actual native mesh and collider changes."""

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sys

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.lab import command, snapshot, step
from experiments.phase2_controls import reset, near

OUT = ROOT / "experiments/desktop/runtime"
OUT.mkdir(parents=True, exist_ok=True)


def save(name, state):
    (OUT / (name + ".json")).write_text(json.dumps(state, indent=2) + "\n")
    return state


def run():
    device = json.loads((ROOT / "experiments/phase2/device.json").read_text())
    report = dict(
        start_utc=datetime.now(timezone.utc).isoformat(),
        **device,
        harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    )
    assert snapshot()["pid"] == device["native_pid"]
    reset()
    command("marker", name="phase2_begin_desktop_bridge")
    batch = next(
        b
        for b in snapshot()["current_room"]["batches"]
        if b["path"] == "segments/basic/basic/start.mesh"
    )
    original = save("00_native_original", command("select", id=batch["id"], box=38))[
        "selection"
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path="/usr/bin/chromium",
            args=[
                "--no-sandbox",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
            ],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto("http://127.0.0.1:8765")
        page.wait_for_function("window.shlab?.state.instances.length === 1")
        page.locator("#box-select").select_option("38")
        for label, value in zip(
            ["Position X", "Position Y", "Position Z"], [0.5, 0, -10]
        ):
            page.get_by_label(label, exact=True).fill(str(value))
        for label, value in zip(
            ["Rotation X", "Rotation Y", "Rotation Z"], [15, 30, 10]
        ):
            page.get_by_label(label, exact=True).fill(str(value))
        for label, value in zip(["Scale X", "Scale Y", "Scale Z"], [2, 0.5, 2]):
            page.get_by_label(label, exact=True).fill(str(value))
        page.locator("#apply").click()
        page.locator("#runtime summary").click()
        page.locator("#refresh-runtime").click()
        page.wait_for_function(
            "document.querySelector('#runtime-target').options.length > 0",
            timeout=120000,
        )
        page.locator("#runtime-target").select_option(str(batch["id"]))
        before_rejection = snapshot()
        project = page.evaluate("window.shlab.project()")
        rejected = page.request.post(
            "http://127.0.0.1:8765/api/runtime/apply",
            data={
                "project": project,
                "instance": project["segments"][0]["id"],
                "native_id": batch["id"],
                "native_pid": device["native_pid"] + 1,
            },
        )
        assert rejected.status == 400 and "process changed" in rejected.json()["error"]
        assert snapshot()["last_command"] == before_rejection["last_command"]
        save("stale_process_rejected", rejected.json())
        with page.expect_response("**/api/runtime/apply", timeout=180000) as response:
            page.locator("#apply-runtime").click()
        applied = response.value.json()
        save("01_bridge_response", applied)
        assert response.value.ok, applied
        native = save("02_native_edited", snapshot())
        selected = native["selection"]
        assert native["pid"] == device["native_pid"] and native["frozen"]
        assert near(selected["position"], [0.5, 0, -10])
        assert near(selected["rotation_degrees"], [15, 30, 10])
        assert near(selected["scale_factor"], [2, 0.5, 2])
        assert selected["mesh_position_checksum"] != original["mesh_position_checksum"]
        assert (
            selected["collider_position_checksum"]
            != original["collider_position_checksum"]
        )
        hit = save(
            "03_native_raycast",
            command("raycast", start=[0.5, 4, -10], end=[0.5, -4, -10]),
        )
        assert hit["raycast"]["hit"] and hit["raycast"]["shape"] == selected["collider"]
        # Repeat from an already edited reference after real world-origin rebasing.
        command("teleport", target="player", position=[0, 1, -60])
        rebased = step(1)
        assert not near(rebased["player_local"], rebased["player_world"])
        with page.expect_response("**/api/runtime/apply", timeout=180000) as repeated:
            page.locator("#apply-runtime").click()
        reapplied = save("04_reapplied_after_rebase", repeated.value.json())
        assert repeated.value.ok, reapplied
        assert near(reapplied["selection"]["position"], [0.5, 0, -10])
        assert near(reapplied["selection"]["rotation_degrees"], [15, 30, 10])
        page.screenshot(path=str(OUT / "desktop-applied-to-game.png"))
        restored = save("05_native_reset", command("reset_object"))["selection"]
        assert near(restored["position"], original["position"])
        # Collider coordinates rebase, so compare vertex checksum before rebasing
        # only for the render mesh, and use pose/native ray tests for colliders.
        assert restored["mesh_position_checksum"] == original["mesh_position_checksum"]
        assert not errors, errors
        report.update(
            result="PASS",
            browser=browser.version,
            checks=[
                "Real browser numeric edits and Apply to game button",
                "Native mesh and collider checksums changed",
                "Original Level raycast hit the edited native collider",
                "Reapplication from edited reference after native origin rebase",
                "Native reset restored original mesh and world position",
            ],
        )
        browser.close()
    command("marker", name="phase2_end_desktop_bridge_PASS")
    report["end_utc"] = datetime.now(timezone.utc).isoformat()
    save("result", report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        save("failure", {"error": repr(error), "native_state": snapshot()})
        raise
