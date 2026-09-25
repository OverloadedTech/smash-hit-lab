# Easier movement in both editors

This page records the archived release named below. The current Android interface and saved editing are documented in [Play/Edit](simple_play.md) and [the editor](editor.md).

This release adds multi-selection and group translation to the existing native Android and desktop editors. It keeps single-object rotation/scaling, real geometry ownership checks, the original gameplay code and the existing project format.

The controls and limits are documented in the [Android editor guide](editor.md) and the [desktop editor guide](desktop_editor.md). Android edits actual loaded source boxes and ordinary scripted bodies. Desktop edits baked boxes and whole segment instances; it does not simulate Lua bodies.

## What changed

- World-axis and view-plane movement handles on Android; a common translation gizmo for desktop groups.
- Relative move buttons, configurable steps, held movement, snapping and keyboard nudges.
- Android segment/current-room/all-loaded scopes and a source-box picker. Desktop current-segment/whole-project box scopes and whole-segment selection.
- One undo action per move, drag, held button, group reset or native bulk apply. Desktop undo also restores the selection after rebuilding project instances.
- Real group bounds and focus. A large selection shows one aggregate bound and up to 64 individual outlines, without reducing the number of edited objects.
- Batched mesh updates and validation before any group member changes. Android updates actual collision geometry along with render vertices.
- Desktop-to-Android API revision 2, which applies a source-box array to an explicit retained native instance with one undo. It uses the actual room transform and origin offset directly.

The normal game libraries and retained assets are unchanged. Developer edits remain local runtime modifications or explicit desktop project data; they are not written into the original game's resume file.

## Verification

**PASS, current Travel release regression, 34 editor checks:** 8 native Android, 7 actual Android UI, 11 desktop browser and 8 desktop-to-Android checks. Native/UI/bridge runs used PID 14443 and APK SHA-256 `1cfe846a63d3a46daf577d045ece235267a822b26ab882a2ce80822c6af31f62`. This includes the added desktop FOV test. Reports are under `experiments/travel_tools/editor_regression/`, with the aggregate at `artifacts/editor-validation-report.json`. These 34 checks are also part of the 55-check [Travel release](travel_tools.md). Native broad selection covered 505 objects; the separately generated UI room contained 463, and the desktop bridge applied 182 source-box edits with one native undo.

**PASS, archived editor release, 33 behavior checks:** 8 native Android, 7 actual Android UI, 10 desktop browser and 8 desktop-to-Android checks. Native/UI/bridge runs used process 8676 and APK SHA-256 `9a7f74d010109d25301ba02a6f498809498997e56068f046f45791a7fe1e9f61`. Its APK, build record and aggregate are retained under `artifacts/releases/editor-groups/`. Both releases compiled both native ABIs; runtime measurements are x86_64 only. The original APK remains `3b2ffa02fee8ca762f40648f1a9bec5c308764e881dd6a79cacd6dccdb16e338`.

The archived Android room/all-loaded scope contained 505 editable objects, including 182 boxes in the starter segment. Desktop group checks covered 364 editable boxes across two segments; live bulk apply changed 182 boxes in one explicitly chosen native instance. These are recorded run counts, not fixed engine limits.

The archived release's measurements remain under `experiments/editor_improvements/`; its aggregate is `artifacts/releases/editor-groups/editor-validation-report.json`. Reports record the APK hash, process identity where applicable, harness hash and individual checks. Aggregation requires the relevant reports to pass and verifies their identity against the delivered APK. It also compares every retained original asset/library and archives the executed harnesses.

The independent checks cover:

| Area | Measured behavior |
| --- | --- |
| Native Android | Mixed static boxes and a real scripted body; mesh/collider changes; native raycasts; group reset/undo/redo; cumulative gestures; pause, revision, PID and invalid-target rejection; broad loaded scopes; origin rebasing; reload/unload invalidation; normal shooting |
| Android touch UI | Real world taps, Multi-select, nudge/hold buttons, undo/redo, an axis drag, a snapped view-plane drag, keyboard input, the source-box dialog and segment/room/all-loaded buttons |
| Desktop browser | Real canvas selection and Ctrl-click, single move/rotate/scale, shared world displacement across rotated and nonuniformly scaled parents, held buttons/keys, actual group gizmo dragging, JSON/GLB reopening, bulk scopes, whole-segment anchors and duplicate/remove history |
| Desktop bridge | A browser group containing 182 source boxes, explicit target/PID guard, native mesh/collider checks and a raycast, one group undo, and repeat application after an origin shift |

See the machine-readable reports for the result and exact instance/count of each run; generated room contents can vary. Compilation alone and displayed controls are not counted as runtime success.

## Failed attempts and corrections

The first installation attempted Android incremental delivery and failed its verification. adb's normal streamed fallback succeeded. Later installs explicitly used `--no-incremental`, preserved Lab application data and verified the installed APK hash.

Startup ANR dialogs occurred on the API 30 software emulator. They were recorded and explicitly dismissed with **Wait** before foreground input verification. A captured candidate trace sampled the main thread waiting in Android HWUI `RenderProxy::setStopped`; its RenderThread was waiting through Android runtime/CheckJNI. That sample does not identify a unique cause. Ahead-of-time DEX compilation did not eliminate every startup dialog. No physical ARM run was available, so physical-device startup/performance remains **UNKNOWN**.

A preliminary native test assumed a scripted body would exist immediately after its first reset tick. The captured room had authored `scoretop` definitions but no created bodies; an additional original update created them. The current harness approaches an observed authored obstacle and advances the original loader if its mixed-selection fixture is not yet present. It never manufactures a test body or counts an uncreated definition as a live object.

An early 1.25-second injected hold advanced only once on the slow emulator. A longer press showed real repeats under one native gesture. The final controls calculate cumulative movement from Android event/uptime timestamps and send the final displacement on release, so delayed callbacks do not silently discard elapsed movement. Repeated unchanged text assignments and the editor header's repeated long/short layout changes were also removed. This is not a claimed physical-device frame-rate benchmark.

One early UI assertion sampled the world before Android's posted Button click callback had reached the native queue. The native event log subsequently recorded the Undo. The reader now waits for the actual native command and checks that the button is enabled. Another attempt queried accessibility while the source dialog was changing windows; the reader now retries the real root rather than treating a missing root as a valid hierarchy. Preliminary failures are preserved separately and are not added to passing counts.

Two retry setup failures came from the retained UI state: Android capitalizes the dialog's Close button to `CLOSE`, and the editor remembers its scroll position. The harness now uses the observed button label and scrolls to the panel's top before selecting its initial checkbox states. Neither failed attempt established new passing editor behavior.

## Reproduce

With the prepared tools and desktop server running:

```bash
source tools/env.sh
export SHLAB_EDITOR_EVIDENCE=experiments/local_editor_check
python tools/android_input.py start --restart
python experiments/prepare_device.py --install --record experiments/local_editor_check/device.json
python experiments/verify_editor_android.py
python experiments/verify_editor_ui.py
python experiments/verify_editor_desktop.py
python experiments/verify_editor_runtime.py
python experiments/summarize_editors.py
```

Run device-mutating checks sequentially. The separate output directory preserves the recorded release evidence. The tests rebuild/teleport the separate Lab run and exercise its real inputs; they do not clear the original game's data. The browser tests require Chromium and the local desktop server. The UI harness defaults to a 1,250 ms injected hold; `SHLAB_UI_HOLD_MS` exists for documented timing experiments.

## Remaining limits

**CONFIRMED:** groups translate while preserving each member's rotation/scale. Rotate or scale one object at a time. Android history is limited to 32 operations and 4,096 selected objects; desktop history holds 50 operations. Reload/unload can invalidate native history. Undo is not a full physics/script snapshot, and scripts or constraints may move bodies after simulation resumes.

**CONFIRMED:** removed baked faces cannot be recovered by moving geometry. In-game duplication/deletion and a full rebaker are still outside this phase. Desktop whole-segment moves also move authored markers, but individual Lua object simulation/editing stays in the real game. Live apply requires one explicitly chosen native segment instance; repeated sources are not automatically paired by guesswork.

**UNKNOWN:** physical ARM behavior, sustained performance on every device, and compatibility with untested game versions/campaign modes. The runtime validates the two inspected original 64-bit engine build IDs.
