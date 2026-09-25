# Developer mode

The addon builds into `artifacts/smash-hit-lab.apk`, package `com.mediocre.smashhit.dev`, with label **Smash Hit Lab**. It installs alongside `com.mediocre.smashhit`; the supplied APK is never overwritten. The normal game implementation and original retained assets/native libraries are copied byte-for-byte. `artifacts/build-report.json` records the input/output hashes and verification count.

## Build and run

The workspace-local tool setup is described in `tools/bootstrap.py`. With those tools present:

```bash
source tools/env.sh
python tools/build_debug.py
adb install -r --no-incremental artifacts/smash-hit-lab.apk
adb shell am start -n com.mediocre.smashhit.dev/com.mediocre.smashhit.MainActivity
```

The native addon builds for the inspected arm64-v8a and x86_64 layouts. Runtime experiments in this workspace use x86_64; arm64 has compilation and static layout checks, without a physical-device test. GNU build IDs are checked before hooks are installed. The builder checks the input APK SHA-256. The developer APK omits 32-bit native variants; the original APK retains all four variants. No offsets are guessed for unsupported ABIs or versions.

The current Android interface is **Play / Edit / Tools**. [simple_play.md](simple_play.md) is the current control guide. New runs can follow rails or move the actual player freely, with independent looking, shooting, stop/reverse and speed/FOV controls. Tools and Edit pause Game/Level simulation. Editing detaches the camera; Save & resume persists supported edits and restores the held gameplay view without music-clock catch-up.

Use **Tools → Explore menu** in the homepage and **Explore transition** during animation. Position bookmarks, XYZ teleport, object metadata, actual current/next room and batch states, room bounds and transition capture are under **Position, rooms & research details**. The normal game is available through **Original game controls · new run**; automatic Play controls can be re-enabled in settings.

The earlier Explore/Travel/Editor tabs documented in archived experiment reports were replaced. Their native automation commands remain available for controlled experiments. Legacy `mode: spectate` deliberately lets the normal player advance while moving only the view; the new UI does not require users to compose these low-level switches.

Stop holds player movement while physics and shooting continue. Tools/Edit freeze Game updates, including Level, Scene, Menu and Display. Music continues independently. In current Play mode, progression uses native simulation dt, so resuming after a long edit does not catch up to the music-driven rail position. Raw legacy commands can still select the original coupling for research.

The editor selects and changes real retained native geometry. Direct dragging, optional handles, multi-select, whole-room moves, Undo/Redo and exact single-object transforms share the same native implementation. [editor.md](editor.md) describes mapping, persistence and geometry limits. The desktop interface is described in [desktop_editor.md](desktop_editor.md).

## Implementation boundaries

Two calls are added to activity creation: `DevBridge.prepare` loads and initializes the addon before the native game starts; `DevBridge.install` attaches the overlay after the original activity initialization. An activity key-dispatch override forwards developer keys and delegates all other keys. A new DEX and `libshdev.so` implement the overlay and instrumentation. No game library instructions are rewritten. The addon resolves exported functions and redirects their ELF relocation slots to wrappers. The first-person projectile guard also explicitly patches the verified Body update vtable relocation; ordinary hooks retain their existing PLT/GLOB relocation scope. With the corresponding developer/practice features off, wrappers call the original functions. C1/D1 relocation symbols matter even when C2/D2 aliases share the same address.

Commands are parsed on the UI/receiver side and queued. The original game/render thread drains the queue at a frame boundary, so vertex uploads, entity mutations, reloads and snapshots do not race render jobs. A short mutex protects command transfer and the published JSON string; it is not held while native simulation/rendering runs.

The free camera temporarily replaces render-time pose/projection state only during `Game::draw`, then restores it. Player teleports separately enable a manual hold at the original progress-query boundary; see `camera.md` for its precise intervention and release semantics. Enabling or disabling developer mode clears the original pause through `Game::setPaused(false)`; the developer freeze then owns simulation stopping. The original gameplay HUD remains visible during Play and is hidden during inspection/editing. Simulation freezing gates Game::update, covering native Level, Scene, Menu and Display updates. It preserves the original startup counter if an update slot is skipped. It does not stop the Android activity, the outer audio update or every platform/UI callback. Music time is logged because it can independently trigger room preparation on a later simulation step.

Native tutorial triggers and tutorial input/update handling are suspended while developer mode is active. The original tutorial trigger helper can pause the game and write tutorial-completion state, so the addon skips that whole helper instead of silently completing prompts. Disabled wrappers call the original tutorial code. Step and simulation-resume controls release an existing native pause through its original API; pending step batches continue to release that pause until their requested updates finish. Snapshots separately report the native pause flag/fade, active tutorial ID, number of skipped tutorial checks, and original player mode. The normal tutorial system remains available after exiting the tools.

## Automation and logs

`tools/lab.py` sends the same commands as the UI through an adb-forwarded abstract Unix socket. The app checks peer credentials and accepts only its own UID, root or the Android shell UID. A dynamically registered receiver requiring `android.permission.DUMP` provides a slower fallback. The app opens no TCP listening socket. The optional host-side forward listens on localhost port 18765.

```bash
python tools/lab.py forward
python tools/lab.py snapshot
python tools/lab.py command '{"op":"mode","value":"inspect"}'
python tools/lab.py command '{"op":"teleport","target":"camera","position":[10,12,-40]}'
python tools/lab.py step 1
python tools/lab.py screen inspection.png
python tools/lab.py log experiment-events.jsonl
```

JSON snapshots and rotating event logs live in the app's private `files/shdev/` directory. Snapshots include normal and developer poses, accumulated origin, current/next rooms, obstacle definition state, render batch load flags, body/entity counts, RSS/virtual memory and timestamps. Commands carry request IDs for asynchronous acknowledgement. Room constructor/destructor and batch-load wrappers record actual calls; UI labels are not used as evidence for native lifetime.

The legacy export command creates `files/shdev/edits.json`. Current Save operations write validated source overrides to `files/shdev/level-edits.json`; preferences use `controls.json`. These use atomic private-file replacement and do not modify the original game save. A developer can retrieve it with `adb exec-out run-as com.mediocre.smashhit.dev cat files/shdev/edits.json`. Event logs rotate at 8 MiB per file, retaining two archives; oversized old files retain only their newest complete records after upgrade. Periodic samples omit bulky editor arrays. `tools/lab.py log` collects available archives oldest first; stop the app before copying if an exactly stable capture is needed. Full detailed snapshots remain available through the API.

The APK uses a local development signing key generated under `build/`; it does not have the original publisher signature. Normal local gameplay and remote platform-service compatibility are separate verification questions. Current verification is described in [simple_play.md](simple_play.md). `experiments.md`, `phase2_experiments.md` and the older editor/travel reports retain evidence for their own recorded builds.

For the known laboratory emulator, `python experiments/prepare_device.py --install` installs, waits for fresh socket telemetry, starts the separate Android input test helper, enters normal gameplay through real injected touch input, and verifies the installed APK hash. Optional `--aot` forces ahead-of-time Java compilation; it is slow on software emulation and did not eliminate all startup ANRs. Preparation is deliberately separate from normal phone installation instructions: its Start-button coordinates are for the documented 960×540 emulator. `experiments/run_experiments.py PHASE` runs controlled checks against that initialized app.

`python experiments/run_suite.py` runs all phases sequentially and stops on a failure. The optional preparation flag `--clean-data` clears only `com.mediocre.smashhit.dev`; use it for a fresh tutorial/profile experiment after copying out laboratory logs and exports. Recorded final-run identity comes from the installed APK and live PID, with a harness hash in each result. `experiments/analyze_events.py` extracts phase intervals into JSONL, a CSV timeline and measured event summaries.

The UI experiment helper is `experiments/input_driver/DevInput.java`, started with `python tools/android_input.py start`. It runs under the adb shell/root identity and injects `MotionEvent`/`KeyEvent` through Android InputManager. Its abstract Unix socket accepts only shell/root peers and is forwarded to localhost port 18766. It is not packaged in the game, grants the game no input-injection permission, and is unnecessary for ordinary phone use. The persistent helper avoids repeated app_process startup delays in software emulation. APK-native commands still use the separate in-game queue on port 18765.

Helper version 4 can also read the real Android accessibility hierarchy through UiAutomation, without requiring the periodically refreshed telemetry panel to remain idle for one second. The reader is external to the APK; UI tests still inject actual touch/key events. It omits password text. No game accessibility or input-injection permission is added.


A fresh source-only checkout also needs locally generated mappings. Install Python dependencies, use `tools/bootstrap.py` for the Linux build toolchain, and run `python tools/prepare_input.py` against your own exact APK before building. [public_repository.md](public_repository.md) provides complete setup commands. The desktop application can launch with only its smaller Python/Three.js dependencies; it does not need an Android emulator for static editing.
