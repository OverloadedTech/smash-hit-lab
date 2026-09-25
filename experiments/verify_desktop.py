#!/usr/bin/env python3
"""Exercise real desktop UI and inspect changed GPU/export vertex data."""

from pathlib import Path
import hashlib
import json
import struct
import sys
from datetime import datetime, timezone

import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.assets import Assets

OUT = ROOT / "experiments/desktop"
OUT.mkdir(exist_ok=True)


def read_glb(path):
    data = path.read_bytes()
    magic, version, size = struct.unpack_from("<III", data)
    assert (magic, version, size) == (0x46546C67, 2, len(data))
    n, kind = struct.unpack_from("<II", data, 12)
    assert kind == 0x4E4F534A and n % 4 == 0
    doc = json.loads(data[20 : 20 + n])
    m, kind = struct.unpack_from("<II", data, 20 + n)
    assert kind == 0x004E4942 and m % 4 == 0 and 28 + n + m == len(data)
    binary = data[28 + n :]
    assert len(binary) >= doc["buffers"][0]["byteLength"]
    for view in doc["bufferViews"]:
        assert view.get("byteOffset", 0) % 4 == 0
        assert view.get("byteOffset", 0) + view["byteLength"] <= len(binary)
    return doc, binary


def position_data(doc, binary, mesh_index=0):
    accessor = doc["accessors"][
        doc["meshes"][mesh_index]["primitives"][0]["attributes"]["POSITION"]
    ]
    view = doc["bufferViews"][accessor["bufferView"]]
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    return np.ndarray(
        (accessor["count"], 3),
        dtype="<f4",
        buffer=binary,
        offset=start,
        strides=(view["byteStride"], 4),
    ).copy()


def run():
    report = {
        "start_utc": datetime.now(timezone.utc).isoformat(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "checks": [],
    }
    archive = OUT / "harnesses"
    archive.mkdir(exist_ok=True)
    (archive / (report["harness_sha256"] + ".py")).write_bytes(
        Path(__file__).read_bytes()
    )
    assets = Assets(ROOT / "com.smash.hit.apk")
    report["input_sha256"] = assets.sha256
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
        assert page.locator("#catalog-count").inner_text() == "643"
        # Actual mouse ray selection; choose a visible floor face away from the gizmo.
        canvas = page.locator("#world").bounding_box()
        page.mouse.click(
            canvas["x"] + canvas["width"] * 0.65, canvas["y"] + canvas["height"] * 0.80
        )
        selected = page.evaluate("window.shlab.state.selection.ordinal")
        assert selected is not None, "Canvas ray did not select a source box"
        report["checks"].append({"ray_selection": selected})
        page.locator("#box-select").select_option("38")
        assert page.locator("#apply").is_enabled()
        page.wait_for_timeout(300)
        center = page.evaluate("""() => {
            const p=window.shlab.gizmo.worldPosition.clone().project(window.shlab.camera);
            const r=document.querySelector('#world').getBoundingClientRect();
            return [r.x+(p.x+1)*r.width/2,r.y+(1-p.y)*r.height/2];
        }""")
        handle = None
        for distance in [25, 40, 55, 70, 85, 100]:
            page.mouse.move(center[0] + distance, center[1])
            if page.evaluate("window.shlab.gizmo.axis") == "X":
                handle = [center[0] + distance, center[1]]
                break
        assert handle, "No visible X transform handle was pickable"
        page.mouse.down()
        page.mouse.move(handle[0] + 40, handle[1], steps=10)
        page.mouse.up()
        dragged = page.evaluate('window.shlab.project().segments[0].edits["38"]')
        assert dragged and abs(dragged["position"][0] - 0.5) > 0.1
        report["checks"].append({"gizmo_mouse_drag": dragged})
        page.locator("#undo").click()
        page.wait_for_function(
            "!window.shlab.state.loading && Object.keys(window.shlab.project().segments[0].edits).length === 0"
        )
        page.locator("#box-select").select_option("38")
        initial = np.array(
            page.evaluate("Array.from(window.shlab.geometry())"), dtype=np.float32
        ).reshape(-1, 3)
        box = assets.metadata("basic/basic/start")["mapping"]["boxes"][38]
        target = [
            float(box["position"][0]) + 1.5,
            float(box["position"][1]) + 2,
            float(box["position"][2]) - 1,
        ]
        for label, value in zip(["Position X", "Position Y", "Position Z"], target):
            page.get_by_label(label, exact=True).fill(str(value))
        for label, value in [
            ("Rotation X", 0),
            ("Rotation Y", 90),
            ("Rotation Z", 0),
            ("Scale X", 2),
            ("Scale Y", 0.5),
            ("Scale Z", 1.5),
        ]:
            page.get_by_label(label, exact=True).fill(str(value))
        page.locator("#apply").click()
        changed = np.array(
            page.evaluate("Array.from(window.shlab.geometry())"), dtype=np.float32
        ).reshape(-1, 3)
        indices = np.array([q * 4 + i for q in box["quads"] for i in range(4)])
        original = initial[indices] - box["position"]
        scaled = original * np.array([2, 0.5, 1.5])
        expected = scaled[:, [2, 1, 0]] * np.array([1, 1, -1]) + target
        assert np.allclose(changed[indices], expected, atol=1e-5)
        others = np.ones(len(initial), dtype=bool)
        others[indices] = False
        assert np.array_equal(
            changed[others], initial[others]
        ), "Unselected geometry changed"
        report["checks"].append(
            {
                "numeric_edit": "Actual selected vertices moved/rotated/scaled; all other vertices unchanged",
                "vertices": len(indices),
            }
        )
        page.screenshot(path=str(OUT / "desktop-box-edit.png"))
        page.locator("#undo").click()
        page.wait_for_function(
            "!window.shlab.state.loading && Object.keys(window.shlab.project().segments[0].edits).length === 0"
        )
        assert np.array_equal(
            np.array(
                page.evaluate("Array.from(window.shlab.geometry())"), dtype=np.float32
            ).reshape(-1, 3),
            initial,
        )
        page.locator("#redo").click()
        page.wait_for_function(
            "!window.shlab.state.loading && Object.keys(window.shlab.project().segments[0].edits).length === 1"
        )
        report["checks"].append({"undo_redo": "PASS"})
        page.get_by_label("Project name").fill("verified-desktop-project")
        with page.expect_download() as download:
            page.locator("#save").click()
        project_file = OUT / "verified-project.shlab.json"
        download.value.save_as(project_file)
        project = json.loads(project_file.read_text())
        assert project["segments"][0]["edits"]["38"]["position"] == target
        assert (ROOT / "desktop/projects/verified-desktop-project.shlab.json").exists()
        with page.expect_download() as download:
            page.locator("#export").click()
        glb_file = OUT / "verified-project.glb"
        download.value.save_as(glb_file)
        doc, binary = read_glb(glb_file)
        assert np.array_equal(position_data(doc, binary), changed)
        assert doc["extras"]["shlab_project"] == project
        report["checks"].append(
            {
                "export": "GLB vertices exactly match edited renderer buffer; texture and editable project embedded"
            }
        )
        page.locator("#box-select").select_option("")  # Whole-segment actions require that selection level.
        page.locator("#duplicate").click()
        page.wait_for_function("window.shlab.state.instances.length === 2")
        page.locator("#delete").click()
        page.wait_for_function("window.shlab.state.instances.length === 1")
        page.get_by_label("Search segments").fill("basic/basic/stairs2")
        page.locator('[data-source="basic/basic/stairs2"]').click()
        page.wait_for_function(
            "window.shlab.state.instances.length === 2 && !window.shlab.state.loading"
        )
        page.locator("#restitch").click()
        stitched = page.evaluate("window.shlab.project()")
        assert stitched["segments"][0]["position"] == [0, 0, 0]
        assert stitched["segments"][1]["position"] == [0, 0, -32]
        report["checks"].append({"add_duplicate_remove_stitch": "PASS"})
        page.locator("#project-file").set_input_files(str(glb_file))
        page.wait_for_function(
            "window.shlab.state.instances.length === 1 && !window.shlab.state.loading"
        )
        assert page.evaluate("window.shlab.project()") == project
        assert np.array_equal(
            np.array(
                page.evaluate("Array.from(window.shlab.geometry())"), dtype=np.float32
            ).reshape(-1, 3),
            changed,
        )
        report["checks"].append(
            {"reopen_glb": "Project and actual edited geometry restored"}
        )
        captured_file = ROOT / "experiments/controlled/D0_camera_baseline.json"
        captured = json.loads(captured_file.read_text())
        batches = [
            (room, b)
            for room in [captured.get("current_room"), captured.get("next_room")]
            if room
            for b in room["batches"]
        ]
        page.locator("#run-file").set_input_files(str(captured_file))
        page.wait_for_function(
            f"!window.shlab.state.loading && window.shlab.state.instances.length === {len(batches)}"
        )
        imported = page.evaluate("window.shlab.project()")
        for item, (room, batch) in zip(imported["segments"], batches):
            assert item["source"] == batch["path"].removeprefix(
                "segments/"
            ).removesuffix(".mesh")
            assert item["position"] == [
                0,
                0,
                room["world_z_bounds"][1] + batch["offset"],
            ]
        report["checks"].append({"captured_native_layout_import": len(batches)})
        page.locator("#project-file").set_input_files(str(glb_file))
        page.wait_for_function(
            "!window.shlab.state.loading && window.shlab.state.instances.length === 1"
        )
        page.locator("#flight").check()
        before = np.array(page.evaluate("window.shlab.camera.position.toArray()"))
        page.locator("#world").click(position={"x": 30, "y": 150})
        page.keyboard.down("w")
        page.wait_for_timeout(1000)
        page.keyboard.up("w")
        page.keyboard.down("e")
        page.wait_for_timeout(500)
        page.keyboard.up("e")
        after = np.array(page.evaluate("window.shlab.camera.position.toArray()"))
        assert np.linalg.norm(after - before) > 1 and after[1] > before[1]
        report["checks"].append(
            {"desktop_flight": {"before": before.tolist(), "after": after.tolist()}}
        )
        page.screenshot(path=str(OUT / "desktop-verified.png"))
        assert not errors, errors
        report["browser"] = {
            "version": browser.version,
            "page_errors": errors,
            "renderer": "Chromium WebGL / SwiftShader",
        }
        browser.close()
    # Validate every mesh in the complete catalogue export independently of the UI.
    all_file = ROOT / "artifacts/smash-hit-all-segments.glb"
    doc, binary = read_glb(all_file)
    assert len(doc["extras"]["shlab_project"]["segments"]) == 643
    vertices = triangles = 0
    for number, node in enumerate(doc["nodes"]):
        source = node["extras"]["source"][len("segments/") : -4]
        _, v, t = assets.mesh(source)
        p = position_data(doc, binary, node["mesh"])
        assert np.array_equal(p, v["p"]), source
        primitive = doc["meshes"][node["mesh"]]["primitives"][0]
        a = doc["accessors"][primitive["indices"]]
        view = doc["bufferViews"][a["bufferView"]]
        index = np.frombuffer(
            binary,
            dtype="<u4",
            count=a["count"],
            offset=view.get("byteOffset", 0) + a.get("byteOffset", 0),
        )
        assert np.array_equal(index.reshape(-1, 3), t)
        vertices += len(p)
        triangles += len(t)
    assert (vertices, triangles) == (3475048, 1737524)
    report["checks"].append(
        {
            "full_catalog_glb": {
                "segments": 643,
                "mesh_nodes": len(doc["nodes"]),
                "vertices": vertices,
                "triangles": triangles,
                "bytes": all_file.stat().st_size,
                "sha256": hashlib.sha256(all_file.read_bytes()).hexdigest(),
            }
        }
    )
    report["result"] = "PASS"
    report["end_utc"] = datetime.now(timezone.utc).isoformat()
    (OUT / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run()
