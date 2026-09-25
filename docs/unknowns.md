# Known limits and open questions

The following sections describe Smash Hit; the other games have their own scope at the end. The APK version, custom native architecture, major asset formats, 64-bit object layouts, static streaming predicates and working native box/body editing have been established. The notebook and experiment report distinguish static evidence from runtime measurements.

## Runtime coverage

- **CONFIRMED limit:** runtime tests use the shipped x86_64 engine on an API 30 AOSP emulator with software CPU emulation and SwiftShader. arm64-v8a is compiled and its used layouts/control flow were compared statically; no physical ARM device has been tested.
- **UNKNOWN:** compatibility across every Android/GPU version and frame rate. Software-emulator startup can be slow and has produced Android ANRs; recovery is recorded separately from controlled measurements. Captured Android HWUI/runtime waits do not establish a unique cause for every startup interruption.
- **UNKNOWN:** exhaustive behavior of every game mode, later boss, credits, endless-generation branch and possible script. Three Classic starter-room rebuilds produced three distinct layouts; this does not establish randomness or determinism for every generator/mode.
- **UNKNOWN:** remote billing, ads, achievements, cloud saves and publisher services under the development package/signature. Local gameplay verification does not test these services.
- **CONFIRMED / UNKNOWN boundary:** the inspected local profile/quick-save paths use reversible obfuscation without a MAC or digital signature. Cloud progression sync and the separate premium cache are traced statically in [saves and integrity](saves_and_integrity.md); edited-save acceptance, server-side score validation, interrupted-write recovery and conflicting XML-attribute behavior have not been tested dynamically.

## Editing and rendering

- **CONFIRMED limit:** saved source overrides now replay matching static boxes and authored ordinary bodies on future runs, including a new process. Transient/unowned bodies without stable identities remain runtime-only. There is no complete offline XML-to-mesh rebaker; saved body edits do not relocate their original spawn threshold.
- **CONFIRMED limit:** ambiguous or unmatched baked faces remain inspect-only. Original hidden/internal faces that were removed during baking do not reappear after moving a box. Decals, reflection masks, UVs and baked lighting are not regenerated.
- **CONFIRMED limit:** special ball/model bodies use a separate render path and are inspect-only. Ordinary scripted polyhedron bodies and mapped static boxes have working native transform editing; every possible material/fragmentation combination has not been tested.
- **CONFIRMED scope:** both editors now support multiple selections, real draggable translation handles, step/held movement controls and group undo/redo. Individual rotation/scale remains supported. Groups translate while retaining each member’s rotation/scale; general group rotation/scaling is not implemented. In-game duplication/deletion and a complete rebaker remain unimplemented. Desktop duplication/removal operates on whole segment instances, and Lua anchors are not individually simulated bodies. See [current editing](editor.md) and the [archived editor improvements](editor_improvements.md).
- **UNKNOWN:** full semantics of every shader/material flag, reflection effect and LjusBus effect under arbitrary camera orientations. Inspection fog/culling options improve visibility but do not reconstruct the renderer.
- **CONFIRMED limit:** camera obstruction with noclip off uses a native point raycast, not a swept player capsule. Noclip is available for the detached camera and actual-player flight.

## Streaming and persistence interpretation

- **CONFIRMED:** a raw player-position write can be reclaimed by the original rail update. The developer's Hold player control explicitly suppresses that movement at the progress-query boundary; its state and corrections are logged. This intervention preserves original streaming conditions but must be stated when interpreting teleport experiments.
- **CONFIRMED limit:** a farther clipping plane or turned camera cannot recreate destroyed geometry. Manual reverse travel now explicitly reconstructs preceding native RoomDefs, and level/room jumps use the original reset path. There is still no backward state cache: broken glass, script state and random choices are not restored. Matching saved/staged source edits can reapply to rebuilt content. First-person player balls use bounded cleanup; original controls and ordinary fragments retain original cleanup. See [travel tools](travel_tools.md).
- **UNKNOWN:** exact allocator reuse/fragmentation after long sessions. Native destructors and resource identifiers establish object lifetime; RSS need not decrease when memory is freed.
- **UNKNOWN:** complete original source organization and provenance of every Qi/td subsystem. Exported symbols, examined call sites and bundled library version strings provide a substantial architecture map, not a full recovered source tree.
- **UNKNOWN:** semantic names of both leading UFNT font-header values. Raw values and glyph records are preserved and validated.

Controlled streaming and input results are maintained in [experiments.md](experiments.md). An unrun or failed check is retained as such; it is never relabeled as successful based on the implementation alone.

Expanded feature verification is tracked separately in [phase2_experiments.md](phase2_experiments.md). The desktop GLB contains static baked geometry, not a complete scripted/physical game. Catalogue stitching is an artificial sequence, not a canonical generated campaign. The public bundle contains tools/docs and requires a separately supplied APK. Original tooling and notes now use the [MIT license](../LICENSE).

The [Play/Edit release](simple_play.md) uses native-timestep player movement and separate paused editing semantics. A native PC port remains a separate deferred phase.

## Other Mediocre games

Granny Smith and PinOut now have embedded developer APKs and a shared desktop
scene editor; see the [developer-kit guide](other_game_devkits.md) and the
[technology comparison](mediocre_comparison.md). Independent native collision
queries verify that editing changes real collision geometry. PinOut also has
16 passing controlled streaming checks; Granny Smith's embedded addon has
measured live Box2D steps. Historical failed debugger attachments remain
failures and do not supply that evidence.

- **CONFIRMED limit:** Granny Smith has 2D gameplay physics. The camera moves
  in 3D, but the player stays in X/Y; X/Y mesh tilt does not add 3D collision.
  Scaling dynamic or jointed terrain is rejected before applying a group edit.
- **CONFIRMED limit:** PinOut body edits rebuild native collision triangles and
  buffers, but do not regenerate joint anchors, mass/inertia or baked lighting.
- **CONFIRMED limit:** both save pose overrides against native level/table and
  body identities. They are not complete source XML editors or mesh rebakers.
- **UNKNOWN:** exhaustive later-level behavior, every special entity and every
  device/GPU combination. ARM64 builds have static layout and symbol checks;
  no physical ARM64 device has been available for runtime testing.
- **UNKNOWN:** an equivalent verified Granny Smith fog switch, safe general
  object creation/deletion and full save-format/remote-service behavior for
  either new game. The individual research documents separate mapped fields
  from these open questions.
