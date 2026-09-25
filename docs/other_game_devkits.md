# Granny Smith and PinOut developer kits

These addons run inside the original Android engines. They use separate app
IDs, original game libraries and assets, and an embedded `libmlab.so`; no root,
Frida server or desktop connection is required for the on-device tools.
Smash Hit retains its existing [Play/Edit interface](simple_play.md).

| Lab | Compatible input | Included native architectures | Android minimum |
| --- | --- | --- | --- |
| Granny Smith Lab | Granny Smith 1.3.8 / 10308 | ARMv7 and ARM64 | 5.0 / API 21 |
| PinOut Lab | PinOut 1.0.7 / 1000700 | ARM64 and x86_64 | 8.0 / API 26 |

Inputs are checked against the SHA-256 values in the individual game research
documents. The loader also checks the native library's full hash. Support for
another release cannot be inferred from a matching game title.

## Start here

Install the local `artifacts/granny-smith-lab.apk` or
`artifacts/pinout-lab.apk`. The apps are named **Granny Smith Lab** and
**PinOut Lab** and install alongside the original games. Each has its own saves.

The small top bar is available in the menu and in gameplay:

| Control | Behavior |
| --- | --- |
| **LAB** | Opens tools and pauses the world when entered from gameplay |
| **Play** | Returns to the original camera and input, and releases the Lab pause |
| **Camera** | Detaches the view and pauses the world; fly without moving the player |
| **Edit** | Pauses and opens object editing |
| **Run / Pause** | Toggles world simulation independently of the current view mode |

Opening the tools does not accumulate gameplay time for a later catch-up.
The original frame loop continues so rendering, input and commands remain
responsive. The addon gates gameplay updates separately. Audio can continue.
An original tutorial or pause screen can also hold gameplay; **Run** releases
the Lab pause, not every original game's modal screen.

## Fly, look around or move the player

Choose **Camera**, drag an empty part of the screen to look, and hold
**Forward / Back / Left / Right / Up / Down** to fly. **Look behind** turns
the view 180 degrees. The free camera has no world collision.

**LAB → Look around + play** lets the normal game run while the view follows
the player with an independent orientation. **LAB → Move player** controls
the actual character or ball. **Noclip when moving player** disables the
relevant player collision while this mode is active. Leaving it restores the
normal collision path.

The games have different physical worlds:

- **Granny Smith:** the character moves in X/Y. The native Box2D character has
  no independent gameplay Z position. The inspection camera can still fly in
  all three dimensions, behind scenery and outside the corridor.
- **PinOut:** the ball moves in X/Y with Z as height. Player controls use the
  table's axes; moving forward changes Y. The camera can fly independently in
  arbitrary 3D directions.

**Fly speed**, **Look sensitivity** and **World speed** are separate settings.
The FOV slider controls horizontal field of view in the Android renderer.
PinOut exposes **Show distance fog** when the real fog shader was intercepted.
Granny Smith does not show a fog switch: an equivalent verified shader control
has not been established for that game.

With a keyboard: **WASD** moves, **Q/E** moves down/up, arrow keys turn the view,
**Space** toggles pause, **F1** opens tools and **Escape** returns to Play.
The touch controls remain available without a keyboard.

## Drag and save geometry

Enter **Edit**, close its side panel, and drag a visible body. Selection uses
the actual native render triangles; a green outline identifies the selection.
Dragging translates in the camera's screen plane. Reopen **Edit** to inspect
the selected body's native ID, type, level/table, transform, buffers and
collider information.

**Add objects to selection** enables multi-selection. **Select all loaded**
selects the captured native bodies together. The XYZ step buttons, rotation
buttons and scale buttons transform the selection as a group. A drag is one
undo operation. **Undo / Redo** work on whole group operations. A single body
also has numeric XYZ position, rotation in degrees and scale fields.

Choose **Save selection** to keep the selected poses for future native loads
and future app launches. These are app-private overrides in
`files/mediocre-lab/level-edits.json`, keyed by real level/table identity and
native body order. **Reload level** exercises the original reload/reset path
and reapplies saved overrides. To restore original geometry, use **Clear saved
overrides**, then **LAB → Reload level**.

These overrides do not rewrite the APK's original XML or cache files. Dynamic
bodies and scripts may move edited objects after simulation resumes.

### Geometry and collision limits

**CONFIRMED:** Granny Smith edits call the original `Body::setTransform` and,
for supported scaling, `Body::updateGeometry`. The renderer and Box2D fixture
are updated together. Static bodies without native joints support scaling;
unsupported group scaling is rejected before any member is changed. Z
rotation affects 2D collision. X/Y tilt and depth affect presentation, not
a new three-dimensional Box2D world.

**CONFIRMED:** PinOut edits change the native body transform and its real
vertex-buffer range, including geometry baked into shared table buffers.
Scaling changes collision vertices and rebuilds the native `QiDbvt3` triangle
tree. Selection also works on visible bodies that have no per-mesh collider.
The table's implicit floor is not an editable mesh object. Joint rest anchors,
mass/inertia, baked lighting and Lua behavior are not regenerated by moving
or scaling a body.

Neither addon invents editable entities for every decal, particle, UI element
or procedurally rendered effect. Creating arbitrary new asset types, source
XML rebaking, safe object deletion and joint authoring remain future work.

## Levels, teleportation and streaming

The **Teleport** fields accept native world coordinates. Move the camera or
the player independently. **Save camera spot / Restore spot** bookmark the
view. Teleporting does not rewind physics, score or script history.

Granny Smith lists all 57 campaign levels, using their real native paths.
Selecting one runs the original loader. Its current scene is displayed as a
whole level; the UI does not invent a chunk stream.

PinOut lists the current run's 125 ordered table entries. A table button
moves the actual ball into that table and invokes native streaming. The list
shows current/active/ready states, loading stage and body counts. Active
geometry is completed by the original synchronous activation path even while
the Lab world is paused. Previously cached inactive tables can remain resident.
The measured algorithm is described in the PinOut notes, which are not part of
this repository.

The direct level/table controls bypass the normal selection flow for local
research; they do not modify purchases or account entitlements. Granny Smith
provides **Prevent character death**; PinOut provides **Unlimited time**,
matching the actual failure mechanism each switch affects.

## Desktop and research data

The [native scene desktop editor](native_scene_editor.md) connects to either
running Lab through ADB, displays its real triangles, and applies or saves
object/group edits back to the game. The on-device **Export scene JSON**
button produces the same format.

**Copy Lab files** copies exported scenes, events and edits to the app's external
files directory. Internal files are under `files/mediocre-lab/`:

- `events.jsonl` and rotated logs: timestamps, commands, native load/unload
  events and adapter-specific physics observations.
- `scene.json`: exported native triangles, current body poses and level metadata.
- `level-edits.json`: saved object pose/scale overrides.
- `preferences.json` and `camera-bookmark.json`: view/speed preferences and the
  saved camera pose.

Live snapshots are available through the local socket and Java bridge. They
include player/view poses, original engine state, selected objects, loaded
level/tables, update counters and native library/source identities. The
experiment scripts record these snapshots to JSONL on the host.

Android object, level and section lists have search and twelve entries per
page. This limits Android layout work while keeping every captured entry
accessible. **Select all loaded** still selects the entire loaded collection.
The live status strip reads a compact cached snapshot; opening or refreshing
a panel reads the complete research snapshot. Unchanged status text is not
parsed and laid out again on every poll. Panel lists describe that captured
snapshot; use **Refresh list** after loading or moving to another section.

The log is bounded to three approximately 8 MiB generations. Scene exports
contain game geometry and stay local; they are excluded from the public source
bundle.

The native abstract sockets are `pinout_lab` and `granny_smith_lab`. They accept
the app itself or local Android shell/root clients. The desktop server binds
to loopback only. No network service, cloud account or game executable is
reimplemented for this workflow.

## Build and evidence

The builder lives in the two addon repositories, since the adapter sources are
there rather than here. After the [Linux toolchain setup](public_repository.md),
provide the original at the private input path and run, from a
[granny-smith-lab](https://github.com/OverloadedTech/granny-smith-lab) or
[pinout-lab](https://github.com/OverloadedTech/pinout-lab) checkout:

```sh
source tools/env.sh
python tools/build_game_lab.py granny-smith
```

The builder downloads a hash-pinned Dobby dependency, compiles each supported
ABI, signs a separate development package and checks retained game assets and
libraries byte for byte. Keep `build/mediocre-lab.keystore` private and retain
it for compatible Lab updates. Build reports contain original/output APK
hashes and a fingerprint of the compiled sources.

The integration experiment is
[verify_game_lab.py](../experiments/verify_game_lab.py). It must run on a
dedicated test installation: its explicit `--allow-reset` flag clears Lab
overrides and changes the active run. Assertions use live native state and
the original game's collision-query functions, not just UI labels.

Runtime validation uses API 23 ARMv7 for Granny Smith and API 26/30 x86_64 for
PinOut. ARM64 builds are compiled and independently mapped, but have not been
tested on a physical ARM64 device. PinOut's final API 26 emulator needed a
SystemUI workaround after independent boot ANRs. The release experiment
guide, [game_lab_experiments.md](game_lab_experiments.md), records that setup, completed checks and exact
APK identities. Further limits remain in the individual game documents and
notebook.
