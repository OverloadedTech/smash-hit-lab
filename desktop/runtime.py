"""Apply selected source-box edits through the real game's existing editor API."""

import math
import numpy as np
from .assets import KNOWN_APK, rotation


def candidates(snapshot, source):
    return [
        {
            "id": batch["id"],
            "room": room["index"],
            "room_instance": room["id"],
            "path": batch["path"],
            "offset": batch["offset"],
            "world_z_bounds": batch["world_z_bounds"],
        }
        for room in [snapshot.get("current_room"), snapshot.get("next_room")]
        if room
        for batch in room["batches"]
        if batch["loaded"] and batch["path"] == "segments/" + source + ".mesh"
    ]


def connected(source):
    from tools.lab import forward, fast_request

    forward()
    state = fast_request("GET")
    if not state.get("installed"):
        raise ValueError("Open the Smash Hit Lab APK on the connected Android device")
    return {
        "pid": state["pid"],
        "playing": state.get("playing", False),
        "frozen": state.get("frozen", False),
        "editor_api_version": state.get("editor_api_version", 1),
        "segments": candidates(state, source),
    }


def euler(matrix):
    """YXZ Euler angles, matching the native editor and desktop transforms."""
    x = math.asin(float(np.clip(-matrix[1, 2], -1, 1)))
    if abs(math.cos(x)) > 1e-6:
        y = math.atan2(matrix[0, 2], matrix[2, 2])
        z = math.atan2(matrix[1, 0], matrix[1, 1])
    else:
        y = math.atan2(-matrix[2, 0], matrix[0, 0])
        z = 0
    result = np.degrees([x, y, z]).tolist()
    if not np.allclose(rotation(result), matrix, atol=2e-5):
        raise ValueError("Unsupported native room transform")
    return result


def apply(assets, body):
    from tools.lab import command, fast_request, forward

    if assets.sha256 != KNOWN_APK:
        raise ValueError(
            "Live application requires the exact APK used by this native Lab build"
        )
    project = assets.validate_project(body["project"])
    item = next((s for s in project["segments"] if s["id"] == body["instance"]), None)
    if not item or not item["edits"]:
        raise ValueError("Select a segment containing edited source boxes")
    identity = int(body["native_id"])
    expected_pid = int(body["native_pid"])
    forward()
    state = fast_request("GET")
    if state.get("pid") != expected_pid:
        raise ValueError("The game process changed; refresh the loaded segment list")
    if not state.get("playing"):
        raise ValueError("Start a level in the connected game first")
    if identity not in {s["id"] for s in candidates(state, item["source"])}:
        raise ValueError(
            "That matching segment is no longer loaded; refresh the target list"
        )
    command("mode", value="inspect")
    state = fast_request("GET")
    if state.get("pid") != expected_pid:
        raise ValueError(
            "The game restarted before applying edits; refresh the target list"
        )
    if identity not in {s["id"] for s in candidates(state, item["source"])}:
        raise ValueError(
            "The segment unloaded before the world paused; refresh the target list"
        )
    if state.get("editor_api_version", 1) >= 2:
        # Native code knows the actual instance's room transform, source offset
        # and origin rebase. Validate all targets, then update meshes/colliders
        # once per segment; one native Undo restores the entire operation.
        state = command(
            "apply_box_edits", id=identity, expected_pid=expected_pid,
            edits=[{
                "box": int(ordinal), "position": edit["position"],
                "rotation_degrees": edit["rotation"], "scale": edit["scale"],
            } for ordinal, edit in item["edits"].items()],
        )
        return {
            "applied_boxes": len(item["edits"]), "native_id": identity,
            "pid": state["pid"], "selection": state["selection"],
            "selection_group": state["selection_group"],
            "world_paused": state["frozen"], "single_undo": True,
            "scope": "Source-box edits in the chosen live segment. Desktop segment placement is not applied.",
        }
    if len(item["edits"]) > 128:
        raise ValueError("This older APK supports at most 128 box edits; install the current Lab APK for bulk apply")
    boxes = assets.metadata(item["source"])["mapping"]["boxes"]
    # Obtain the true native source-to-world transform from a source box in its
    # baseline pose. This also works after origin rebasing or rotating a room.
    reference = int(next(iter(item["edits"])))
    previous = command("select", id=identity, box=reference)["selection"]
    if not previous.get("editable"):
        raise ValueError("The native game cannot edit this mapped segment")
    base = command("reset_object")["selection"] if previous["changed"] else previous
    matrix = rotation(base["rotation_degrees"])
    origin = np.asarray(base["position"]) - matrix @ np.asarray(
        boxes[reference]["position"]
    )
    operations = []
    for ordinal, edit in item["edits"].items():
        operations.extend(
            [
                {"op": "select", "id": identity, "box": int(ordinal)},
                {
                    "op": "transform",
                    "position": (
                        origin + matrix @ np.asarray(edit["position"])
                    ).tolist(),
                    "rotation_degrees": euler(matrix @ rotation(edit["rotation"])),
                    "scale": edit["scale"],
                },
            ]
        )
    try:
        for offset in range(0, len(operations), 32):
            state = command("batch", commands=operations[offset : offset + 32])
    except Exception:
        # Undo the reference reset if conversion/application failed before it
        # received its requested transform. Other already-applied boxes remain
        # visible and can be reset using the game's normal editor controls.
        command(
            "batch",
            commands=[
                {"op": "select", "id": identity, "box": reference},
                {
                    "op": "transform",
                    "position": previous["position"],
                    "rotation_degrees": previous["rotation_degrees"],
                    "scale": previous["scale_factor"],
                },
            ],
        )
        raise
    return {
        "applied_boxes": len(item["edits"]),
        "native_id": identity,
        "pid": state["pid"],
        "selection": state["selection"],
        "world_paused": state["frozen"],
        "single_undo": False,
        "scope": "Source-box edits in the chosen live segment. Desktop segment placement is not applied.",
    }
