# Runtime architecture

**CONFIRMED from symbols, dependencies, DEX, and disassembly:** Smash Hit 1.5.14 uses a native C++ custom engine. The Android layer uses Google's `GameActivity`; this is not Unity or Unreal. Exact historical names/provenance of all internal libraries remain unknown.

`MainActivity` extends `com.google.androidgamesdk.GameActivity`, loads `libsmashhit.so`, and integrates analytics, remote configuration, billing, ads, achievements, leaderboards, and cloud saves. Its code is preserved in decoded DEX and the JADX output. JADX reported 123 decompilation errors overall; no claim is made that its generated Java is compilable original source.

The native entry is `android_main`, with a `Renderer` managing EGL/window lifecycle and a `Game` instance holding the main systems. Exported `gGame` provides a runtime inspection foothold. `Game::frame`, `Game::update`, `Display::update`, `Game::draw`, `Level::update`, and `RenderLevel::draw` organize simulation and presentation.

| Layer | Observed facilities |
| --- | --- |
| Shared engine (`Qi*`) | Vectors/quaternions/transforms, arrays/strings, allocators, files/streams, XML, Lua integration, graphics buffers/shaders/textures, audio, threads/jobs, sockets, spatial trees |
| Embedded standard libraries | Lua 5.2.0, zlib 1.3.1, libpng 1.6.42, libVorbis 1.3.7; JPEG decoder; C++ runtime |
| Physics facilities | `td*`, `TdSolver`, GJK/EPA/MPR-related routines, `Polyhedron`, `QiDbvt3` |
| Game-specific systems | `Game`, `Level`, `Room`, `Obstacle`, `Body`, `Shape`, `Player`, `RenderLevel`, `LevelScript`, breakage/scoring/balls/powerups |
| Additional content systems | `LjusBus` effects, OBJ model providers, ball model/style configuration, tutorials |

The distinction between shared engine and game code is based on actual call sites and data responsibilities. Source repository boundaries are not available.

**CONFIRMED:** `Scene` represents scripted UI/menu scenes, while native gameplay uses `Level` and its entity/room collections. The name `Scene` must not be mistaken for a Unity-like universal scene graph. `Player` is primarily profile/progression/save state; the spatial position governing normal movement resides on `Level`.

**CONFIRMED:** `Editor::init`, `Editor::update`, and `Editor::draw` are empty in this APK. `Debug` retains more substantial debugging helpers, but enabling the existing editor state does not produce a working level editor.

Resource lifetime uses `ResMan`, reference-counted resources, explicit destructors, and `QiAlloc`/`QiFree`. Lua states have their own garbage collection. Rendering uses worker jobs for some buffer filling, then waits before issuing draws. Game object mutations must occur outside those jobs on the native game thread.

Android audio uses OpenSL ES through the native audio layer. Sound banks decode effects through Vorbis; music maintains streamed PCM buffers and a played-byte clock. Native pause stops that audio clock, while the addon's simulation freeze leaves it running (audio is updated by the outer frame loop). This distinction is observable and affects when the next room is prepared.

First-run tutorials are another game-specific runtime system. `TutorialUtils::checkTutorialTriggers` inspects configured obstacle proximity and completion state; `TutorialManager::startTutorial` invokes callbacks that pause gameplay and display HUD hints. `Game::updateTutorial` handles the required touch/hit and completion. These are separate from Level's movement and from the developer freeze. Their debug-mode isolation is documented in `developer_mode.md`.

Native networking includes reusable TCP/UDP/HTTP facilities and `ResMan::load` supports an explicit `http://` resource path. Their presence alone does not prove gameplay fetches levels over the network. Bundled level assets are local. Managed networking supports Google/Firebase/platform services; remote service success in a rebuilt APK has not been verified.

Ghidra's import base is `0x100000`; subtract it from exported decompilation addresses to obtain ELF-relative addresses. Original ELF exports, disassembly, and runtime experiments take precedence over inferred Ghidra prototypes.

The expanded addon gates Game::update to cover menu rotation and scene/level ticks, preserves the native startup counter when an update slot is skipped, and adds optional actual-player flight and single-player practice controls. These are isolated interventions around the original code. See [menu exploration](menu_and_transitions.md), [resume](quick_resume.md), the [engine walkthrough](engine_walkthrough.md) and [second-phase verification](phase2_experiments.md).

The current phone interface is [Play/Edit](simple_play.md). Its movement controller uses native simulation dt, while the inspection camera has a separate pose. Opening Tools or Edit gates Game/Level updates; Resume restores the held player view. Original-controls new runs use the original stop/start lifecycle. `play.*`, `navigation.*`, `editor_*`, `projectiles.*`, `graphics.*`, `storage.*` and `diagnostic_log.*` isolate the addon's respective responsibilities. Source-transform sidecars belong to the addon and are distinct from original player saves.
