# What happens to balls after they fall?

**CONFIRMED (native control flow):** a projectile is a native Body/Entity with a ball-specific flag and rendering path. The game does not keep every fired ball in active physics forever. Removal from the physics world and destruction of the owning entity are separate events.

`Physics::update` examines eligible active dynamic bodies without a parent or joints. Its shape-bound checks include an upper Y bound below -10 and a Z-bound test against the normal level pose. A matching condition clears the body's active flag and calls `Physics::remove(Body*)`. This unregisters the body from active physics; it is not by itself proof that the Entity/Body allocation has been freed.

Separately, `Level::update` removes eligible level-owned entities once their minimum Z lies behind the normal progression pose. It calls the real destruction path. A fallen ball ahead of a held player can therefore be inactive yet retained until progression passes it. The predicate uses the exact shape bounds; testing only the center against -10 would not reproduce it.

`Body::update` increments an age counter. No age-based expiry was found in that function; do not infer a universal ball lifetime from how long it remains visible. Rendering, fog/culling, physics membership and allocation lifetime must be inspected separately.

## Instrumentation and experiment

Snapshots now include `balls_in_world` with IDs, position, active state, age and velocity. The native `Physics::remove(Body*)` wrapper records `ball_removed_from_physics`; `Level::destroy` records the actual `entity_destroy` call and whether it is a ball.

`experiments/phase2_controls.py balls` moves the actual normal pose outside the corridor, creates a ball with real Android touch input, then holds the player while allowing original physics updates. It records the ball becoming inactive, tests whether it stays allocated without moving, and moves the player past it to test destruction. This is an experiment procedure. [phase2_experiments.md](phase2_experiments.md) records its measured result, which does not cover every possible ball/material.

These observations describe the original cleanup path. The current first-person mode keeps original projectiles and physics but adds the bounded exception described below; original controls retain the native thresholds. Memory counters are supplementary: a native object can be destroyed while the allocator retains the freed pages, so RSS need not decrease immediately.

## Measured result

**CONFIRMED (runtime, 2026-09-07):** on the expanded APK `ea95c6d995c79caad3bdc08291a23f42569d66a26c5f5a66ceaa5a05630955f5`, process 2571, a real touch-created ball with ID 198 became inactive at world position `(31.9943, -10.4811, -45.9158)`. The player remained held near `(30,15,-4.9417)`. After another 60 original updates the same ball ID remained in the native body list at exactly that position; its age advanced from about 6.6 to 12.6. Moving the player past it to Z=-50.9158 and permitting one update removed that ball ID from the owned-body list.

This demonstrates a retained, inactive body rather than immediate object destruction at the below-world threshold. The measured age continuing to increase does not imply continuing physical movement. The snapshot chain is `experiments/phase2/ball_*.json`; `ball_lifecycle_summary.json` preserves the selected body and comparison values. Native cleanup events provide the separate call-level evidence.

The event stream places the first `Physics::remove` call at native update 584, ball age about 2.2. The later `Level::destroy` call occurs at update 689 and explicitly identifies ball 198; destruction also invokes Physics::remove again. These are distinct calls about 31.46 wall-clock seconds apart in this stepped emulator experiment. That elapsed time is a property of the test schedule, not a built-in projectile timer.

## First-person play exception

A controlled backward shot exposed both original forward-only retirement rules: a ball shot toward +Z was retired even while close to a stationary player. The new Play mode temporarily guards the entity-bound test and the exact Physics retirement call site for in-range player balls. Actual bounds are restored before physics; original collisions, breakage, velocity integration and destructor calls remain native. This guard is disabled in original-controls runs and does not apply to ordinary fragments.

The addon retires first-person balls at 15 native seconds, 100 units from the player, when inactive, or above a cap of 256. The oldest over-cap balls are removed first. These are explicit developer-mode limits, not recovered original constants. Runtime checks have confirmed backward flight, flight below Y=-10, distance retirement, restored bounds and original inventory use. See [Play/Edit verification](simple_play.md).
