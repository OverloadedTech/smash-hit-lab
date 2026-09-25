# Player and progression

**CONFIRMED:** the native `Player` object stores profile/progression fields, modes, room index and persistent game state. `Game + 0x60` points to it; its room index is at `+0x8b0` and mode at `+0x974` in the inspected 64-bit builds. The normal spatial position used by streaming is on `Level`, not a generic movable player-body entity.

The shipped `menu/main.lua` defines training=0, classic=1, expert=2, zen=3, versus=4 and cooperative=5. These modes affect generator seeding, room length and other gameplay branches. The addon reports the original numeric mode and does not change entitlement checks.

The game moves a normal camera/progression pose down the path. Projectile balls, obstacles, powerups and other effects are separate entities. `Level::handleInput` can spawn a ball even if `Level::update` is frozen, which was observed with the original runtime probe. Inspection/editing therefore suppresses this handler. Current first-person Play calls it with the gameplay view and original input queue so native shots, inventory and powerups remain functional.

Research snapshots call the level progression pose “player” to distinguish it from the detached camera. Teleporting this target writes the real Level pose and enables an explicit developer hold, because the original music-driven movement otherwise reclaims a position-only write. The hold is shown in the UI and telemetry and is released when leaving developer mode. Normal loading logic runs on the next permitted simulation update; a frozen teleport by itself does not perform a simulation update. Step controls make this distinction observable.

Displayed distance and physical path coordinates are different. One original runtime sample reported Z = -25.7992 and displayed distance = 43.8587. Room XML display-length metadata can differ from the Lua-computed physical room length. No universal meter-to-score conversion is assumed.

With practice options off, normal mode delegates to the original gameplay handlers. This addon does not unlock paid modes or modify entitlements. The developer build uses a separate package ID and local signature, so platform billing/cloud service success must not be inferred from gameplay success on the AOSP emulator.

## Current first-person player controls and practice options

Current **Rails / Free move** controls write the actual Level spatial pose, preserve it at the progress-query boundary and allow native streaming/physics/scripts to run. The attached view can look in any direction. Rail movement uses native dt and the chosen path speed/direction. Stick/WASD, UP/DOWN and Q/E move relative to the view plus world vertical. **Stop** holds the player while looking/shooting/physics continue. **Edit / Tools** instead freeze the world and allow detached-camera inspection.

Noclip skips the flight obstruction ray and suppresses normal corridor-hit penalties while actual-player flight is active. **Immortal** is a separate single-player option: it suppresses hit penalties/game-over handling and keeps at least one ball. **Unlimited balls** retains the pre-shot inventory and maintains a minimum supply. Neither option changes premium entitlements. They remain active after leaving DEV so the original aiming/shooting controls are usable, and their checkboxes in Tools report their state. They reset when the process restarts. Their scope is the native single-player modes 0–3.

**Resume** returns to the held position and gameplay view, using native-timestep travel without music catch-up. **Original game controls · new run** restarts a clean run before restoring the original camera/input path. The legacy API can still explicitly release a held out-of-bounds pose to original movement; that research operation can reclaim Z through the old rail clock. Reverse traversal reconstructs prior RoomDefs and reapplies matching saved source edits, without restoring previous script/physics state.

The ball count is the game's resource; there is no invented hit-point field. Original `hitSomething` ordinarily removes up to ten balls and resets the streak, with mode-dependent exceptions. Controlled damage probes call that real function; they are identified as probes rather than claimed as physical collision tests. See [second-phase experiments](phase2_experiments.md).

Original automatic quick-save/resume is documented in [quick_resume.md](quick_resume.md).
