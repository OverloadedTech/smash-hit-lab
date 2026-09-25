# Second-phase experiments

This report covers the expanded menu/player/immortality/desktop/resume work. First-phase results refer to the separately archived first release and remain in [experiments.md](experiments.md). Do not apply a first-release test result to a different APK hash without a new measurement.

The later individual/bulk editor improvements have their own [release evidence](editor_improvements.md). This phase's APK, build record and aggregate are preserved under `artifacts/releases/phase2/`; the measurements below remain tied to that earlier APK.

The corrected expansion APK is SHA-256 `ea95c6d995c79caad3bdc08291a23f42569d66a26c5f5a66ceaa5a05630955f5`. Tests use the real shipped x86_64 engine on an API 30 AOSP emulator at 960×540 with software CPU emulation and SwiftShader. arm64-v8a is compiled and checked statically; no physical ARM test has been performed here.

`experiments/phase2_controls.py` archives its own hash, records full native snapshots, and marks phase begin/end in the native event stream. Each result carries the installed APK hash and process identity. `experiments/verify_desktop.py` drives real Chromium controls and compares actual renderer/export geometry with the APK.

## Recorded results

| Check | Status and evidence |
| --- | --- |
| Homepage and both transition directions | PASS on PID 12674; native tick survives freeze, fully displayed homepage, camera outside menu, midpoint capture and fixed transition while camera moves |
| Actual player flight | PASS on PID 12674; lateral/vertical movement, cruise across room boundary, backward movement, pause, switch to independent camera |
| Immortality and unlimited balls | PASS on PID 2571; native hit 25→15, suppression at 15, damage restored when disabled, real last-ball shot retains 1, real unlimited shot retains 25 |
| Fallen ball lifecycle | PASS on PID 2571; real shot becomes inactive below the world, remains motionless/allocated for 60 more updates, then disappears from owned bodies after player passes it |
| Native box/body editor regression | PASS on PID 2571; mesh/collider transforms, original raycasts, resets, segment reload and level rebuild |
| Warm versus cold resume | PASS; PID 4286 retained exact XYZ, room instance, balls and edit on Home/reopen; new PID 4696 rebuilt room 1 at its entrance with saved balls and original geometry |
| Streaming and camera/noclip regression | PASS on PID 4696; original 129/131/161 boundary outcomes, six camera-only poses with actual updates, obstruction with collision on and passage with noclip |
| Desktop geometry editing and GLB | PASS; actual ray selection and gizmo mouse drag, numeric transforms, unchanged unselected vertices, undo/redo, save/reopen, segment operations, captured-layout import and flight |
| Complete catalogue export | PASS; all 643 meshes and triangle arrays compared with the APK |
| Desktop-to-game application | PASS on PID 4696; browser Apply changed native mesh/collider data, original raycast hit that shape, application worked again after origin rebasing and native reset restored the mesh; stale-process request rejected before any native command |
| Expanded Android UI controls | PASS on PID 4696; visible DEV/Explore/preset buttons, real keyboard player motion, pause versus camera-only inspection, both cheat switches, normal-control badge and disabling both options |
| Clean source reproduction | PASS; all 643 uncached box mappings matched, local inputs regenerated, both native ABIs built/signed and 2,433 retained original asset/library entries verified |

This table is updated from results, not from UI presence or successful compilation.

The local aggregate is `artifacts/phase2-validation-report.json`. `experiments/summarize_phase2.py` checks release hashes and archived harnesses, identifies the seven native phase intervals by their actual log markers, and rejects malformed lines within those intervals. UI/browser checks and the clean-source build are categorized separately. `experiments/phase2/events-verified.jsonl` contains the selected native records with process and phase annotations; the original raw log is retained unchanged.

The completed aggregate contains 11 passing checks across those categories and 2,151 verified native events in the seven marker-bounded phases. These numbers do not include preliminary failures as passes. Physical ARM testing, full campaign/mode coverage and original remote-service compatibility remain outside the measured scope.

## Failures and experiment corrections

The first transition helper used a different native campaign-start function and produced an invalid Classic room. It was changed to the same RestartLevel selector used by the Classic menu. An early startup ANR report lacked an app stack, so its cause remains unassigned.

Whole-world freeze initially skipped native updates but allowed the outer frame loop to decrement its startup counter. Direct process-memory inspection measured native tick -4,585. The loading logo persisted. The correction preserves the last executed update's tick when an update slot is skipped; original unmodified frames retain the native adjustment. Homepage verification was repeated on the corrected APK rather than reusing the misleading early menu-state check.

An initial flight test attempted a checkpoint rebuild while still in the menu. The harness now enters a game first, and the addon rejects that invalid operation with a clear message.

An initial unlimited-shot check ran after a slow emulator screenshot. Normal gameplay reached tutorial 1 and paused, preventing the expected shot. The last-ball shot had already succeeded. The corrected test resets between shot cases so tutorial-specific input cannot be mistaken for a cheat failure. Normal tutorials remain functional after leaving DEV.

A second shot pilot touched the screen immediately after a native mode command, before the Java overlay had finished handing input back. A native pick-command error identified the stale developer view. The successful test waits for the overlay poll before injecting a normal gameplay shot.

The first cold-resume assertion incorrectly expected the post-rebuild score to remain identical to the serialized score. Native quickLoad did restore score 340, but Level::reset rebuilt room 1 at its entrance and Level::update copied that displayed distance, 272, back into Player. The failed assertion is preserved; the corrected experiment verifies both the loader event and the subsequent recalculation.

The long-running emulator process exited during the next test's setup; adb reported offline and then no device. There was no exit explanation in its saved log, and the host had ample free memory/disk when checked. The event is recorded as an environment interruption with unknown cause. Previously completed APK/PID measurements remain separate from later runs on the restarted emulator.

Raw preliminary snapshots and logs are retained under `experiments/phase2/preliminary/`. An unrun or failed assertion is never silently counted as a passing test.

The append-only log contains one damaged older line (3,666 bytes at offset 8,081,981 in the PID 12674 block, including 3,523 null bytes), observed after the emulator interruption. Its exact cause is unknown. Later process blocks begin with explicit instrumentation/PID headers. The process-scoped reader reports gaps outside the requested process and rejects any damaged line inside that process. The cold-resume result uses an intact PID 4696 block; it does not silently repair the older record.

The first expanded UI check found an existing Android ANR dialog instead of DEV. The event was timestamped 19:25:15, during the preceding cold startup, and named the original AppMeasurementService. Its saved trace includes the native game thread decoding the original Vorbis sound bank while loading the menu scene. This is not evidence that the desktop bridge or a particular developer button froze the UI. The dialog was explicitly dismissed with its Wait button after startup, with the failure hierarchy/screenshot preserved. UI tests are repeated against the usable foreground activity; software-emulator cold-start timing remains a documented limitation.

The standard uiautomator dump subsequently failed its idle wait because the developer panel refreshes repeatedly. That command left an older hierarchy file in place, so the failed attempt is retained and not used as successful UI evidence. External input-helper version 3 reads the actual accessibility hierarchy directly without an idle wait. The final UI run used that hierarchy to locate buttons, injected real touch/key events, and verified the corresponding native state. Initial UiAutomation connection can briefly have no active root; the reader waits for the actual root rather than inventing coordinates.
