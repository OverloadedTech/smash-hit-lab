# Runtime experiments

This is the **archived first-release report**. Its APK is retained at `artifacts/releases/phase1/smash-hit-lab.apk`. The second-phase measurements are in [phase2_experiments.md](phase2_experiments.md). The current interface and APK verification are described in [simple_play.md](simple_play.md); the main artifact path points to the current build. Each report is evidence for its recorded APK, not automatically for later builds.

**CONFIRMED:** all 15 controlled phases below passed against the built and installed laboratory APK. This includes real Android touch/key input, native mesh and collider changes, detached camera movement with actual streaming updates, forward/backward player teleports, and resumption of normal gameplay. The scope is the tested x86_64 runtime, not every device or game mode.

## Reproducible identity and method

| Item | Recorded value |
|---|---|
| APK | `artifacts/releases/phase1/smash-hit-lab.apk` |
| SHA-256 | `b7e1d9cc43308cc824bc2370b5c81b6b11cf927ae12a8e61a5dffd2e22053aa6` |
| Package / native PID | `com.mediocre.smashhit.dev` / `8899` |
| Original native build ID | `ac3b897010a22367c4829bf6429e90e74f5b0fce` |
| Runtime | API 30 AOSP x86_64; 960×540; software CPU emulation; SwiftShader; no KVM |
| Controlled measurements | 2026-09-06, 23:14:04–23:39:21 UTC; individual intervals in `result_*.json` |
| Mode / profile | Classic, native mode 1; laboratory app data cleared before this build's run |

The result files and screenshots named in this report, under `experiments/` and `artifacts/`, are produced locally when the harnesses run and are not part of the source release. `device.json` records the installed APK identity. Each phase result includes that hash, PID, UTC interval, native time/frame interval and the SHA-256 of its test harness. Exact harness versions are archived in `experiments/harnesses`. The APK did not change between these phases. Harness corrections for Android input timing are described below.

The automation uses the same native command queue as the in-game UI. It waits for request acknowledgement and reads native snapshots. UI phases additionally inject real Android `MotionEvent`/`KeyEvent` through InputManager; they do not call the transform handler instead of pressing Apply. Scripts, full snapshots and result files are under [experiments](../experiments). Screenshots supplement changed native vertex checksums, actual `Level::raycast` hits and lifecycle calls, which establish world manipulation and resource lifetime.

Each phase starts from the original checkpoint-zero lifecycle and lets pending meshes finish loading unless incremental loading is the variable under test. This resets progression and native instances, but does not impose a fixed RNG seed. Room/obstacle counts can differ across phases. Instrumentation IDs identify instances within this process; native addresses can be reused after destruction.

Developer freeze stops `Level::update`, while rendering and audio continue. Player teleports explicitly enable **Hold player**, which suppresses rail motion at its progress-query boundary while leaving original streaming predicates, music and lifecycle functions active. Camera-only changes never enable that hold. The raw-pose control measures the unmodified rail's response. Developer mode suspends tutorial triggers/input so a native tutorial pause cannot silently stop a requested simulation experiment. Exiting developer mode delegates tutorial handling to the original game again.

## Completed checks

Every row is **CONFIRMED runtime, PASS**. Letters identify snapshot prefixes, not different APK builds.

| Phase / snapshots | Intervention | Measured result |
|---|---|---|
| Normal / A, J | Original rail/camera with updates running; then ten held 50-unit progression increments | Normal world Z advanced from −0.0105 to −147.303; updates 9→571; room 1 prepared ahead of room 0. Ten controlled steps reached Z=−500 and index 3 through intermediate rooms. |
| Raw pose / R | Write player Z=−100 without hold, then one update | Original rail restored Z to −0.01120; camera and room inventory stayed fixed. A position write alone is not a lasting player teleport. |
| Teleport / B, C | Hold player 100 units forward, restore saved origin, then jump 1,000 units forward and return | Z=−100 survived an update; body count 3→8. Expired definitions did not respawn on return. Six updates at Z=−1000 traversed indices 1,2,3,4,5,6. Returning to Z=0 left index 6 current; destroyed rooms were not reconstructed. Camera stayed at `(0,1,0)`. |
| Boundary / K | Hold distance 129, 131 and 161 in a 160-unit room | No next room at 129; next room prepared at 131; current room destroyed/promoted at 161. Music remained below 28 during preparation checks. Strict equality behavior comes from native instructions, not these samples alone. |
| Lateral player / M | Hold player at `(100,1,0)`, `(0,100,0)`, `(0,−100,0)` and execute updates | Normal X/Y movement alone did not change room 0, prepare a next room or alter the settled inventory. Music stayed below its independent threshold. |
| Music / G | Freeze while music passes 28 seconds; permit exactly one update | At music 28.2712, update count remained 639 and no next room existed. One update prepared room 1 at path distance only 0.1422. Its meshes loaded 1→11 while updates remained 640. |
| Stationary player / N | Hold `(0,1,0)`, keep updates running for 51.096 seconds | Updates 641→1179; music 0.8252→32.4508. Room 0 and nine meshes stayed retained; room 1 and eleven meshes were prepared by music. No room was destroyed during the stationary observation interval. |
| Free camera / D, E, F | Freeze player; translate camera, rotate 180°, inspect from above/below, save/restore, continuous diagonal flight | Player, update count and native inventory were identical throughout. Camera reached `(20,15,−60)`, `(0,35,−60)`, `(0,−25,−60)` and `(42.661,43.661,−42.661)`, with vertical/backward orientations. Save/restore returned it to `(0,1,0)`. |
| Camera with streaming / Q | Hold player at origin; camera Z=−1000/+1000, X=100, Y=±100 and backward orientation; one update per pose | Updates 1192→1198; all six updates preserved player and full room/batch/obstacle/entity inventory. Music stayed below 5.47 seconds. This isolates camera position/orientation while streaming logic actually executes. |
| Native editor / H | Ray-select a baked box and scripted body; translate/rotate/nonuniformly scale; raycast, reset, reload, rebuild | Actual render vertices and native collider data changed. Original `Level::raycast` hit the exact edited shape/body. Reset restored checksums; segment reload and native checkpoint rebuild succeeded. |
| Editor after rebase / V | Advance to room 1 with origin Z=−200; move a box far outside the corridor | Box world position changed from `(0,−2.5,−208)` to `(50,50,−205)`, with rotation/scaling. Native raycast hit its exact shape there. Reset restored position and both render/collider checksums. |
| Noclip / O | Fly toward geometry with collision enabled, then noclip | Point-camera obstruction stopped Z near −3.9081. Noclip continued through to Z=−14.0284. Player, updates and inventory stayed unchanged. |
| Touch/keyboard / P | Tap DEV and geometry, hold UP, drag world, press W, open Streaming | UI entry and selection succeeded. UP changed camera Y=1→7.7602; drag produced yaw −33°; W moved to `(3.8422,7.7602,−6.8646)`. Player/simulation stayed fixed. Streaming panel displayed native room/mesh state. |
| UI editor / U | Type position, rotation and scale in Android fields; press Apply and Reset | Typing alone left geometry unchanged. Apply moved the box to `(1.5,−3.5,−14.5)`, rotated Y=30°, scaled Z=2 and changed both native mesh/collider checksums. Reset restored both. |
| Normal-mode regression / I, L | Disable tools, wait, shoot with a real screen tap; rebuild checkpoint 0 three times | Free camera/hold disabled; movement resumed to Z=−4.5597. A touch shot reduced balls 25→24 and added a native body. Three rebuilds succeeded with three distinct source/offset layouts. |

## Native geometry evidence

The H box is source `segments/basic/basic/start.xml`, XML child 38. Position changed from `(0.5,−3.5,−14.5)` to `(0.5,0,−10)`, rotation to `(15,30,10)` degrees, and scale to `(2,0.5,2)`. Render-position checksum changed `799652b256f8ce43 → 8d00e6774749f450`; collider-position checksum changed `c59a88b370f113e3 → 7a1b29aacd7d4337`. Native raycast reported the same shape address `0x7166fbb04b80` at the transformed location. Reset restored both original checksums.

The scripted scoretop body moved by +1 on X/Y, rotated `(20,35,−15)` degrees and scaled `(1.5,0.7,1.2)`. Native geometry checksum changed `138af55139aa255a → 5ba6951c83092dcb`. The engine's raycast hit body `0x7166ab9d7110`; reset restored its geometry. Addresses are scoped to PID 8899, not persistent object IDs.

The V test selected `segments/basic/dark/bs_extraballs.xml` after a native origin shift. At world `(50,50,−205)`, a native ray hit its edited shape near `(50,52.2419,−205.0003)`. This checks the collision tree and coordinate conversion outside the corridor, not just an inspector field.

Screenshots cover the box transform, the body transform, the UI Apply, look behind, above, outside, the streaming UI and normal gameplay restored.

## Streaming interpretation and logs

**CONFIRMED:** room preparation uses either normal path distance or music time; room replacement uses forward path distance and ordered index. There is no general camera-centered 3D chunk cache. Looking behind, flying far away, and moving player X/Y do not request rooms in the tested conditions. A large held player jump catches up one room per native update, constructing intermediate rooms. Going backward does not undo creation flags or reconstruct destroyed rooms.

**CONFIRMED:** retention and normal visibility differ. Loaded batches can fail the normal axial draw test while remaining allocated. Rendering preloads batches without simulation updates, including all eleven next-room meshes in G. Room destruction executes a real destructor. Exact formulas, obstacle expiry and rebasing are in [level_streaming.md](level_streaming.md).

**CONFIRMED:** Classic construction was not deterministic in three checkpoint-zero rebuilds: `experiments/controlled/L_layout_comparison.json` records three distinct hashes, agreeing with the inspected mode-dependent seed branch. This does not establish randomness or determinism for every script/mode.

Raw native logging is retained in `experiments/native-events.jsonl`. `experiments/controlled/events.jsonl`, `timeline.csv` and `event_summary.json` are filtered by the verified PID and each result's time interval. They include room constructor/destructor, batch-load and obstacle-lifetime events, normal/camera coordinates, frame/update numbers, loaded IDs, counts and sampled RSS. Phase summaries include setup/rebuild; use baseline/end snapshot times to isolate an intervention. A setup destructor is not evidence of spontaneous unloading during a stationary test.

Across those intervals, the log contains 287 batch-load calls, all on native thread 8963, with at most one load per room per frame; 35 paired room-destructor begin/end calls, all completed; 11 origin rebases; and 563 memory/state samples. Sampled RSS spans 234,816–270,320 KiB. The stationary N0→N1 interval contains zero room destructors. During the large jump, intermediate rooms 1–5 were destroyed with only 4/11, 3/8, 2/10, 2/10 and 2/12 batches loaded: their native room/collision construction occurred even though rendering did not finish preloading every mesh before the next transition.

## Earlier evidence and corrected failures

The supplied original APK was run before modification. `experiments/initial_gameplay.json` records pose `(0,1,−25.7992)`, displayed distance `43.8587`, `basic/basic` length 160, nine loaded meshes and four live obstacles. An early Frida freeze produced about 84.3 seconds of stable progression/inventory; later disconnection ends that observation. A later failed Frida attach produced no usable evidence.

An emulator startup timeout was investigated in `analysis/reports/lab-anr-trace.txt`. The game thread was decoding the original Vorbis sound bank; Android also spent time in ART GC/JIT. The trace did not show an addon mutex deadlock. Ahead-of-time Java compilation was used for the controlled emulator. Startup delays are excluded from streaming timing measurements.

`experiments/preliminary` preserves earlier results, including failures. Significant corrections:

- A prototype `Room::createSegment` wrapper had the wrong return type; both ABI signatures were corrected before final-build measurements.
- Native Body bounds did not enclose all rendered polyhedron vertices. Selection uses bounds derived from actual vertices and exposes original stored bounds separately.
- The rail reclaimed a raw player-position write. The visible Hold player intervention provides lasting teleportation; R preserves the raw control.
- Native rebuild follows the current checkpoint selector. An explicit checkpoint-zero restart was added without changing ordinary rebuild semantics.
- An earlier build stopped at a tutorial pause near Z=−25.926. Tutorial triggers/updates are now suspended only in developer mode, and step/resume uses the original unpause API. Final fresh-profile A/J phases completed past that point. `controlled_before_tutorial_fix` retains the failure and its event analysis.
- The first final-build UI attempt tapped a field while Android's keyboard was closing. The editor applied the values entered, but the expected scale was absent. The harness now waits for dismissal; `ui_ime_timing` retains the failed input attempt.
- A first selection tap in another attempt did not appear as a native pick command. Its precise routing cause is **UNKNOWN**, not a confirmed raycast failure. `touch_first_tap_unconfirmed` retains it. Successful P records actual world taps and native selection.

## Limits

ARM64 was compiled and its used layouts/signatures checked statically, but was not run on a physical device. Tests cover Classic starter rooms and traversal through index 6, not all bosses, scripts, modes, GPUs or remote services. Software-emulator timing is not a performance benchmark. RSS cannot prove that every freed resource returns pages to the OS. Runtime edits are not durable asset recompilation; destroyed rooms remain unavailable until a native rebuild. See [unknowns.md](unknowns.md).
