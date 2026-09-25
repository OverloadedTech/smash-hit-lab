# Mediocre game technology comparison

Research dates: 2026-09-08–09. This compares the supplied APKs, not every historical
version of these games. **CONFIRMED** means directly observed in the files or
in the explicitly identified runtime experiment. Static findings are not
automatically runtime test results.

## Inputs and current status

| Game | Supplied version | Native game library | Packaged ABIs | Status |
| --- | --- | --- | --- | --- |
| Smash Hit | 1.5.14 | `libsmashhit.so` | ARM64, ARMv7, x86, x86_64 | Play/Edit addon built; 72 behavior checks and logger checks passed on x86_64 |
| Granny Smith | 1.3.8 (10308) | `libgrannysmith.so` | ARM64, ARMv7 | Embedded Lab with native object editing, free camera, character controls and a desktop scene editor; ARMv7 runtime checks |
| PinOut | 1.0.7 (1000700) | `libpinout.so` | ARM64, ARMv7, x86, x86_64 | Embedded Lab with native object editing, free camera, ball controls and a desktop scene editor; x86_64 runtime checks |

The ABI column describes the original inputs. Delivered Lab ABIs, controls and
test limitations are documented in the [developer-kit guide](other_game_devkits.md).
The existing Smash Hit APK remains unchanged by the other-game integrations.

Input SHA-256 values:

- Smash Hit: `3b2ffa02fee8ca762f40648f1a9bec5c308764e881dd6a79cacd6dccdb16e338`.
- Granny Smith: `cb5eb4d70bab1b2c9da9210b18dfecbde09314c2efd0fa3288fcbacd55efda03`.
- PinOut: `81c0f9048c2c12731fefcf0373f0fccb28a2e0626288bc826ba66f5002f37ab7`.

## Shared framework

**CONFIRMED, static:** All three use Mediocre's native C++ Qi framework, with
Qi strings, arrays, mathematics, XML, file streams, resource handling, Lua
integration, rendering and audio facilities. Their native imports include
EGL, OpenGL ES 2 and OpenSL ES. The observed entry points and class structure
belong to this custom stack; they are not Unity or Unreal applications.

Comparing ARM64 dynamic exports yields 719 identical Qi-prefixed exported
names across all three, of which 676 contain `::` and describe member or
scoped interfaces. The larger count also includes free functions and globals.
There are 76 shared `td`/`Td`-prefixed names. Names alone do not establish equal
object layouts or prove that every included facility is used during gameplay.

| Pair | Shared Qi-prefixed names | Shared Td-prefixed names | Same-named function byte matches, at least 24 bytes |
| --- | ---: | ---: | ---: |
| Smash Hit / Granny Smith | 724 | 76 | 0 |
| Smash Hit / PinOut | 954 | 107 | 79 |
| Granny Smith / PinOut | 720 | 76 | 0 |

**CONFIRMED:** The Smash Hit/PinOut byte matches include Qi texture/FBO
constructors, viewport picking overloads, marching-cubes setup and XML writer
helpers, as well as third-party library and C++ standard-library routines.
The count does not mean 79 complete engine systems match. Compiler output,
relocations and library versions make unequal bytes inconclusive. No complete
same-path `.so` is byte-identical between the supplied APKs.

The games also reuse some exact assets. Smash Hit and Granny Smith share one
splash sound. Smash Hit and PinOut share 11 asset entries, including a font
atlas, a wait texture, localized promotional textures and two sounds. These
are hash comparisons; the assets remain private inputs to the research repo.

## Important differences

| Area | Granny Smith | Smash Hit | PinOut |
| --- | --- | --- | --- |
| Android host | `NativeActivity`, older Google Play integration | Modern GameActivity host | Modern GameActivity host, Play/Firebase integration |
| Lua version string | 5.1.4 | 5.2.0 | 5.2.0 |
| Gameplay physics evidence | Live Box2D `Step(dt, 5, 2)` measurements and original collision queries | Td solver and 3D polyhedral bodies | `Physics::simulate` generates contacts and calls `tdSolverStep`; original collision queries verify edited geometry |
| Level assets | Gzip XML levels, 2D entity transforms, Lua; binary motion streams | Room scripts, segment XML, cached render batches | XML tables, Lua, compressed geometry and light maps |
| MTX textures | Earlier payload layout | Outer wrapper around JPEG/alpha payload | Same wrapper family as Smash Hit |
| Loading model | Whole level parse and incremental entity initialization; tested far travel retains entity count | Ordered rooms; separate path and music preparation triggers | Ball-Y table selection, active window and incremental preload stages, dynamically tested |
| Native offsets | Separate ARMv7/ARM64 adapter; original body transforms and geometry rebuilds | Existing verified mappings | Separate ARM64/x86_64 adapter; table buffers, collision trees and origin rebasing |

**CONFIRMED, static:** Granny Smith's `b2_version` record contains the three
32-bit integers `2, 2, 1`. Box2D is actually called by its level update. Granny
Smith also contains Td solver and collision exports; it would be inaccurate
to describe its binary as containing only Box2D. Which other paths use Td
requires further tracing.

PinOut's normal update uses ten physics substeps with `Game.dt / 10 * 0.85`.
That call chain actively uses Td. Its table plane is X/Y with Z as height;
Smash Hit advances along its own longitudinal Z convention. Shared math and
solver facilities do not make camera axes or body transforms interchangeable.

Embedded libpng strings identify 1.2.59 in Granny Smith/PinOut and 1.6.42 in
Smash Hit. Granny Smith/PinOut contain the older `20101101 (Schaufenugget)`
Vorbis identification string; Smash Hit contains `20200704 (Reducing
Environment)`. These identify included library builds, not game release dates.

## Asset validation

The reproducible inventory tool is [compare_mediocre.py](../tools/compare_mediocre.py).
It hashes original ZIP entries, examines ARM64 ELF exports and dependencies,
parses XML, and fully decodes JPEG and alpha data for both observed MTX layouts.

| Check | Granny Smith | PinOut |
| --- | ---: | ---: |
| APK files / assets | 961 / 812 | 2,381 / 1,439 |
| XML documents parsed | 115 | 214 |
| Level/table XML roots | 58 levels | 167 tables |
| MTX images decoded | 153, legacy layout | 430, outer wrapper |
| Lua text assets | 44 | 92 |
| GLSL text assets | 16 | 23 |
| Ogg assets | 247 | 78 |

Granny Smith's 66 motion streams now parse completely as six-byte records
with an optional six-float pose: 203,881 records and 40,774 explicit poses.
Input-bit semantics and playback timing remain partially mapped. Its campaign
configuration lists four worlds and 57 level entries, distinct from the 58
packaged level documents. The Granny Smith formats and loading notes are not
part of this repository.

PinOut's 138 geometry files now parse completely into 5,863 mesh records:
132 files use quantized positions and six use an older float layout. All 138
light maps decode to 128 × 256 GL_ALPHA textures. Its campaign has 125 ordered
table references to 122 distinct paths, separate from the 167 packaged table
XML documents. The PinOut formats and streaming notes are not part of this
repository.

**CONFIRMED limitation:** PinOut's original `templates.xml.mp3` has two
`color` attributes on a properties element at line 70. Python's strict XML
parser rejects this document. The original bytes are preserved. The native
parser's choice between those attributes is **UNKNOWN**; a strict-parser
failure is not evidence that the installed game is broken.

## Runtime compatibility

PinOut's unmodified x86_64 build ran its original menu and game on the API 30
laboratory emulator. A read-only baseline observed 125 table loads; the
subsequent controlled study passed 16 checks. Ball Y determines table
selection. Moving the camera, turning backward, or moving the ball only
sideways/vertically did not change streaming. Jumping to table 10 activated
9–12 without loading the intervening tables' authored bodies. Large jumps
retained some old caches; ordinary adjacent progression freed authored bodies
and buffers while keeping table metadata and a generated base body. The
probe held physics while leaving original streaming logic running, then
restored the original pose and simulation. That experiment is recorded in the
PinOut notes, which are not part of this repository.

Granny Smith has no x86 binary. The first ARM64 AVD attempt failed at the
emulator frontend; the direct ARM64 backend then reached Android but failed
in its system runtime before the game could be installed. An official API 23
ARMv7 image and the ARM emulator backend supplied a working environment.
The original Granny Smith menu and first level run there. These separate
environment failures are not game crashes.

Granny Smith's first Frida attachment crashed inside the injected ARM agent,
before the probe ran. Those failed external-debugger attempts remain recorded
in the Granny Smith runtime evidence, which is not part of this repository. The
embedded addon later
provided working measurements: native Box2D steps, actual fixture raycasts,
paused/resumed simulation and saved geometry replay. These are separate
experiments, not reinterpretations of the failed attachments.

## What can be reused

**CONFIRMED:** The Granny Smith and PinOut addons now share the implementation
under `labs/common/`: camera controls, triangle selection, group transforms,
undo/redo, persistence, logging, local transport and the Android interface.
Their desktop scene editor also shares one implementation. APK inventory and
MTX decoding share tooling with version-specific format branches. The existing
Smash Hit tooling supplies the common math and JSON dependencies.

The camera, coordinate axes, player representation, body editing and streaming
must be mapped per game. Granny Smith is a 2D character game and PinOut uses
pinball tables; Smash Hit's player/room offsets and forward cleanup rules do
not transfer directly. A shared framework makes research easier without
making another game's free camera or editor functional automatically.

Promising editor symbols also require inspection: Granny Smith's ARM64
`Editor::init`, `draw`, `update` and undo-state methods are single `ret`
instructions. They are remnants, not an intact hidden editor.

Generated inventories and exact export lists are local at
`analysis/games/comparison/`. Original APKs, assets, native libraries and
decompiler output are excluded from the source-only export. Reproduce with:

```sh
source tools/env.sh
python tools/compare_mediocre.py
python tools/granny_formats.py
python tools/pinout_formats.py
python tools/catalogue_games.py
```

The last command emits one private `catalogue.json` per game. PinOut's catalogue
retains the 125 ordered references and their nine groups, including repeated
paths. Granny Smith's retains the 57 entries and explicit unlock dependencies.
Smash Hit's keeps its room definitions separate from its 643 segment assets;
it does not invent a canonical segment order for procedurally assembled runs.
