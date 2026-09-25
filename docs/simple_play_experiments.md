# Play/Edit release verification

**CONFIRMED (PASS, 2026-09-08.)** This report covers the simplified Play/Edit APK, source-transform persistence and existing desktop/native regressions. It does not inherit an older APK's runtime results.

| Identity | Value |
| --- | --- |
| Delivered APK SHA-256 | `a02ecf9e92601b98b9c13cd569282e3f116bb0789b77c8c61a00c76fdc3824d1` |
| Original APK SHA-256 | `3b2ffa02fee8ca762f40648f1a9bec5c308764e881dd6a79cacd6dccdb16e338` |
| Android package | `com.mediocre.smashhit.dev` |
| Native build ID tested | `ac3b897010a22367c4829bf6429e90e74f5b0fce` |
| Native processes | 26508 before process death; 27131 after reopening |
| Android runtime | API 30 AOSP, x86_64, 960×540, software CPU emulation and SwiftShader |
| Built ABIs | x86_64 and arm64-v8a |
| Retained original assets/libraries | 2,433 entries verified byte-identical |

The exact product source files, compiled libraries, new DEX, original APK, report hashes and process identities are bound by `experiments/summarize_simple_play.py`. Its local result is `artifacts/simple-play-validation-report.json`. Raw measurements and source snapshots are under `experiments/simple_play/candidate-a02ecf9e/`. A preserved release copy is under `artifacts/releases/simple-play/`.

## Completed checks

| Group | Checks | Measured scope |
| --- | ---: | --- |
| Native Play/Edit | 15 | Native-dt rail speeds; Stop; six-axis movement; normalized diagonals; no resume catch-up; native collision versus noclip; reverse seam; turn speed; real shooting/FOV/backward projectile lifetime; shader fog readback; validated settings; individual and bulk persistence |
| Android touch UI | 8 | Actual Stop/Reverse/Look back buttons, stick/vertical/key movement and release, view drag, sliders/fog, direct object dragging, Save & resume/replay, whole-room drag, detached inspection camera |
| Menu and original controls | 4 | Capture/explore/resume both camera transitions, out-of-bounds menu flight, a fresh original-controls run with native camera, shooting, inventory and progression |
| Process-death persistence | 3 | Force-stop/reopen, byte-identical settings and edit records, reconstructed box/body meshes and colliders, bounded diagnostic files |
| Native editor regression | 8 | Mixed body/box transforms and collider hits, one-gesture Undo, reset, invalid-operation guards, bulk scopes, source coordinates after rebasing, selection invalidation on unload, original shooting |
| Desktop editor | 11 | Real browser picking, FOV, individual transforms, groups, held movement, gizmo drag, project/GLB reopening, whole-segment duplicate/remove, input rejection |
| Desktop-to-game bridge | 8 | Actual browser Apply, process guard, 182 native box edits, geometry/collision changes, one Undo/Redo, reapplication after origin rebase and restoration |
| Navigation regression | 15 | View/progression separation, speeds, reverse lifecycle, reversible unlock, rejected requests, all 13 checkpoints, endless continuation, reverse boundaries/start limit, FOV-correct native shots |

All 72 behavior checks passed. The desktop-only group was measured against the same unchanged frontend source and original input APK before the last native restart fix; its source hashes and provenance are retained. It does not claim Android runtime coverage. The Android bridge was rerun against the delivered APK.

The separate C++ logger checks exercise complete-record migration, ordered rotation, per-file/total bounds, restart append, oversized-entry rejection and filesystem errors. Original Play/Edit persistence checks run with replay enabled. Older editor/navigation regressions use original-geometry fixtures with replay disabled so staged edits from one check cannot alter the next fixture; the driver records that setup explicitly.

## Representative measurements

**Pause and resume:** while Edit was open, both world-update counters and the player pose stayed fixed. After the detached camera moved and the test waited 20 seconds, six permitted updates advanced 0.555224 native seconds and moved the player −2.776119 on Z. That matches the starter room's nominal five units per native second. No motion corresponding to the elapsed audio time was applied.

**Direct dragging:** a real screen drag selected mapped source box 177, moving it from `(-3.5, 2.5, -27)` to approximately `(-2, 3.4375, -27)`. Mesh and collider checksums changed, and one Undo restored both. A later whole-room gesture moved 483 currently loaded objects by the same displacement. Reprojection of the picked triangle's anchor measured `(29.999999, -19.999996)` pixels for a `(30, -20)` pixel drag.

**Cold start:** after saving a box and authored scoretop body, the process changed from 26508 to 27131. Preferences and edit records were byte-identical after reopening. New native instances had the expected transforms, matching geometry/collider checksums and original native raycast hits. This verifies geometry application as well as JSON persistence. All three log files remained below 8 MiB.

**Original-controls handoff:** a real confirmation-dialog tap replaced room ID 41 with room ID 57 at the beginning of the campaign. Original forward motion resumed and a real touch shot reduced inventory from 25 to 24. The FPS projectile guard was disabled. A previous candidate's same-state `RestartLevel` call had retained the old room and left a partial transition paused; that failure remains archived.

**Navigation:** every checkpoint from basic through endless created its actual native room, collision shapes and loaded render batches. An endless continuation was also reached at native room index 146. Reverse travel from room 4 to room 3 preserved exactly three requested simulation updates across reconstruction. These are content reconstruction checks, not completed playthroughs of every room or boss.

## Reproduction

Use a prepared compatible emulator, the built APK and the local Android input helper. Set `SHLAB_PLAY_EVIDENCE` to a new evidence directory. Record the installed APK and native PID with `experiments/prepare_device.py`, preserve any startup dialog/recovery, and record the exact compiled sources/build report before running:

```text
experiments/verify_simple_play_contexts.py
experiments/verify_simple_play_cold.py
experiments/verify_simple_play.py
experiments/verify_simple_play_ui.py
experiments/run_simple_play_regressions.py
experiments/summarize_simple_play.py
```

The desktop server must be running for the bridge checks. Desktop-only checks use `experiments/verify_editor_desktop.py` with `SHLAB_EDITOR_EVIDENCE`; retain their source hashes. The cold test updates the evidence directory's device identity for subsequent checks. Do not replace an old report's PID or APK hash to make it appear current.

## Limits

ARM64 has compiled/static verification, not a physical-device run. Startup ANRs occurred on software emulation; the install-time dialog and actual Wait action are retained separately from passing behavior checks. The force-stop/reopen experiment completed without that recovery. Emulator wall time is not phone performance.

Saved edits are source-transform overrides, not a full physics/script save. Reverse reconstructs rooms instead of rewinding prior simulation or random choices. Original missing baked faces, decals, reflection masks and lighting are not regenerated. Native PC execution and developer addons for other games are separate investigations. See [known limits](unknowns.md).
