# Level streaming

The supplied 1.5.14 engine uses ordered forward room progression, incremental mesh preparation, and separate obstacle lifetimes. It does not maintain a general three-dimensional chunk cache around an independently movable camera. The formulas below are **CONFIRMED by native control flow**; the measured consequences and their exact build/runtime coverage are in [experiments.md](experiments.md).

## Coordinates and the normal path

Let `z` be the normal pose Z stored on `Level`, and `r.offset` and `r.length` the current room's native values:

```text
d = -z - r.offset                  physical distance into the room
progress = d / r.length
cz = z + r.offset                  room-local normal pose Z
```

Movement follows negative Z. The native class called `Player` holds profile state; it is not the spatial pose consumed here. Normal movement derives Z from a phase and a smoothed room length, ordinarily `phaseSeconds * smoothedLength / 32`, with music synchronization and special-mode branches. A raw position-only teleport is reclaimed by this rail on the next update. The controlled teleport tests therefore use the explicit developer **Hold player** intervention documented in [camera.md](camera.md). The room-loader predicates, actual music clock, obstacle updates and destructors remain native.

When local Z falls below -50, `Level::centerCamera` shifts rooms, entities and effects and resets normal local Z to zero. The addon accumulates these shifts: `worldZ = localZ + originZ`. Logs contain both coordinate systems. A rebase is not a teleport, a room transition or unloading.

## Room construction and destruction

**CONFIRMED static predicates:** the ordinary update path is equivalent to:

```text
if nextRoom does not exist and (d > current.length - 30 or musicSeconds > 28):
    nextRoom = loadNextRoom(profile.roomIndex + 1)

if nextRoom exists and d > current.length:
    destroy and free currentRoom
    currentRoom = nextRoom
    nextRoom = null
    advance profile room index
    enterRoom(currentRoom)
```

Selection caps at the final level definition; scripts/modes can introduce their own behavior. These are strict `>` comparisons in the examined instructions. The boundary experiments sample either side of the distance thresholds; the exact equality semantics come from the instructions, not from those samples alone.

There is one transition branch per update, without a catch-up loop. A held 1,000-unit forward teleport constructed and traversed intermediate rooms on successive updates. It reached room index 6 after six steps in the recorded starter-level run. The independent camera remained stationary. Intermediate rooms existed even when their mesh preloads did not finish: rooms 1–5 were destroyed with respectively 4/11, 3/8, 2/10, 2/10 and 2/12 batches loaded. Going back to the original world origin did not reconstruct earlier rooms or lower the current index. These are **CONFIRMED runtime results**, not behavior inferred from asset filenames.

There are separate preparation and destruction thresholds: normally 30 units of room overlap, possibly earlier preparation due to music. Room creation runs its Lua generator, resolves the segment XML and creates static collision geometry. Destruction executes the real room destructor and frees its owned obstacles, static body, render batches and other room data. Native destructor control flow includes buffer/resource cleanup; paired runtime begin/end events establish that the destructor actually ran. Process RSS alone cannot establish allocation lifetime because the allocator can retain pages.

## Music and frozen simulation

`QiMusicStream::getLocation` converts played PCM bytes into seconds using sample rate, channel count and 16-bit sample width. `Audio::getLevelMusicLocation` subtracts 0.15 seconds. Crossfades/startup can report negative values, so telemetry deliberately does not clamp them.

Freezing `Level::update` leaves rendering and audio running. A frozen player can therefore hear the music clock pass 28 seconds without a room being constructed: the predicate is evaluated only on an update. Permitting one update then allows the music branch to prepare the next room even while distance is far below `length - 30`. The controlled music and stationary-player tests distinguish this effect from camera movement and from distance-triggered preparation.

## Segment meshes: retained versus visible

Each `mgSegment` appends a render-batch descriptor containing a mesh path and segment offset. The collision shapes already exist after room construction; the mesh's loaded flag is initially false. `RenderLevel::draw` calls `Room::preload` for current and next rooms. Each call loads the first pending batch, so ordinary rendering loads at most one batch per retained room per draw. These calls perform resource loading, zlib decoding and buffer creation synchronously on the caller's game/render thread. This is frame-incremental loading, not evidence of asynchronous mesh I/O. Other rendering buffer-fill jobs are separate and joined before drawing.

Once loaded, a batch stays retained until room destruction or an explicit developer reload. The normal axial draw predicate is:

```text
batch.minZ < cameraInStaticBodySpace.z < batch.maxZ + 25
```

Failing it does not unload the mesh. Frustum clipping is another rendering concern. The Streaming tab distinguishes pending meshes, retained meshes that pass/fail the normal axial test, current/next rooms, and destroyed-room history. Its axial label is not a claim that every triangle is visible on screen. Developer rendering submits all retained batches and allows looking behind; it cannot draw destroyed rooms.

**CONFIRMED runtime:** the final 15 phase intervals contain 287 batch-load calls, all on native thread 8963, with a measured maximum of one load per room per frame. The music experiment increased next-room loaded meshes from 1 to 11 while the simulation update count stayed fixed. The same intervals include 35 completed, paired room-destructor begin/end calls, including setup/rebuilds as well as streaming transitions. The full counts and time intervals are in `experiments/controlled/event_summary.json`; these are observations on a software emulator, not performance estimates for phones.

## Obstacle instances

**CONFIRMED static predicate:** for a normal obstacle definition at room-local Z `oz`, instantiate when `cz < oz + 30`, its instance pointer is empty, and its one-time creation flag is false. Definitions containing `elevator` have a separate earlier pass using 40. XML/script transforms and parameters are used to create actual native entities; there is no invented editor entity graph.

There is no lower distance limit in the spawn branch. A large jump can instantiate already-passed definitions. Their update can then expire them. For a nonempty obstacle, expiry requires every owned entity's minimum Z bound to be at or behind normal Z (`entity.minZ >= z`). Empty/root obstacles have separate behavior. Room update destroys expired obstacles, clears the live pointer, and retains `created_once=true`. Unowned Level entities have a separate `entity.minZ > z` cleanup condition.

The original forward/backward tests confirm that expired definitions stay expired when moving backward within a retained room. Room destruction also destroys its remaining live instances. Hence a retained static corridor can coexist with permanently removed scripted objects behind the player. The later manual [reverse-travel mode](travel_tools.md) is an explicit intervention: it rearms expired authored definitions, mirrors owned-obstacle expiry and rebuilds preceding native rooms. Those modifications must be disabled when reproducing the original streaming algorithm described here.

## Interpretation and scope

Loading depends on the normal path Z and room offset, the real music clock, ordered room index, and whether simulation/draw calls occur. Camera orientation, sideways distance and vertical distance are not parameters to the examined room/obstacle predicates. Detached-camera movement changes rendering only. In addition to frozen-camera inspection, the Q experiment executed six real native updates with the camera at Z=±1000, X=100, Y=±100 and looking backward. Player pose and full inventory stayed unchanged, with music below the preparation threshold. The lateral-player, frozen-music and teleport runs separately isolate normal X/Y, music and path Z.

Room generation can be deterministic without the streaming timings being identical: music time, allowed updates and render frames are distinct clocks. `LevelScript::load` uses a fixed seed in mode 0/capture and a random seed otherwise; Lua scripts may also use their own randomness. Three Classic checkpoint-zero rebuilds produced three distinct layouts. This agrees with the mode-1 random seed path and is not proof about every generator or mode.

Evidence: `analysis/decompiled/{x86_64,arm64}/*Level__update.c`, `loadNextRoom`, `centerCamera`; `Room::{createSegment,update,preload,draw,getProgress}`; `Obstacle::update`; `RenderBatch::load`; `analysis/decompiled/music/`; the controlled snapshots, native events and phase result files under `experiments/`.

## Current Play/Edit tools and interpretation

The original predicates above remain the baseline for the original-mode experiments. Current Play integrates player movement from native dt, holds it across the original music-rail assignment, and optionally reconstructs rooms for reverse traversal. Edit/Tools gate Game updates; camera-only flight does not invoke streaming. Saved overrides apply after native segment/obstacle construction and do not change authored obstacle spawn thresholds. The independent Play/Edit fog switches affect shaders rather than loading.

Use original/legacy controlled modes when reproducing the baseline experiments. A backward reconstruction or saved-override application is an explicit addon event, not evidence that the original game caches old world state. See [current controls](simple_play.md) and the [archived Travel experiments](travel_tools.md).
