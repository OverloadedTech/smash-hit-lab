# Camera and coordinates

**CONFIRMED (static layout and original runtime):** the normal spatial pose is `Level + 0x11c` (three floats) and `Level + 0x128` (quaternion XYZW), on both inspected 64-bit ABIs. This is a level movement/camera pose; the class named `Player` is predominantly profile state. `Display::update` derives the rendered camera, adding gameplay effects. Identity orientation looks along negative Z, X points right, and Y points upward.

The normal level path progresses along negative Z. Its position is derived from a clock and a smoothed physical room length, rather than being an unconstrained transform. Level+0x308 holds a phase in seconds and +0x30c holds a smoothed room length. For ordinary rooms the target distance is `phase * smoothedLength / 32`. With music synchronization active, the phase update uses `0.9 * phase + 0.1 * musicSeconds`; otherwise it advances by the simulation timestep. The length update is `0.995 * oldLength + 0.005 * roomLength`, with capture/boss/credits exceptions visible in the original code. A raw Z=-100 write in the initialized starter room was restored to approximately -0.009 on the next update. The raw-pose experiment and both 64-bit decompilations confirm these facts.

Below local Z = -50, `Level::centerCamera` shifts room/entity/effect coordinates and returns normal Z to zero. Instrumentation maintains `worldZ = localZ + accumulatedOriginZ`. Developer teleport fields, selection positions and saved positions use those stable world coordinates. Native local coordinates and the accumulated shift are also logged. World coordinates are scoped to a level run and reset on an explicit rebuild/jump. Automatic reverse-room reconstruction instead aligns the previous room's exit to the current entrance to preserve the crossing seam.

The addon owns a separate camera position and rotation. Enabling developer mode copies the current displayed pose and freezes simulation. Free-camera movement changes this private pose. It is installed only during the native draw call, along with a longer inspection projection, and restored before control returns to gameplay. The original camera implementation remains present and resumes when developer mode is disabled.

The earlier [Travel implementation](travel_tools.md), retained through the research API, also offers a view attached to the player's real position, with independent rotation and an optional movement offset. This allows looking backward or sideways while the player continues forward. Adjustable native FOV is horizontal, from 20 to 140 degrees, and applies to both normal rendering and its input projection after leaving DEV; Original FOV removes that override. The desktop editor's FOV is vertical, as labeled.

Editor rotation fields are degrees, converted to a normalized quaternion using Y × X × Z composition (yaw, pitch, roll). The UI labels X/Y/Z explicitly. Touch drag and arrow controls constrain pitch just short of its pole; numeric X/Y/Z input accepts a full orientation, including vertical views and looking behind. Movement uses the rotated local forward/right vectors plus world-up vertical controls. The legacy camera API uses 3 world units per second at 1x. The current Play/Edit UI exposes movement directly in units per second (default 6). Large wall-time stalls are clamped for interactive movement; teleport fields provide exact positioning.

With noclip enabled, movement bypasses collision checks. With noclip disabled, a native level raycast limits each movement step. This is a point-camera test, not a reconstructed character controller or swept capsule. Flying into a room that has been destroyed shows no geometry. Camera movement alone does not issue load requests.

**CONFIRMED runtime:** the camera, touch/key, noclip and live-streaming camera phases passed on the final x86_64 APK. In the live-streaming phase, six original updates with camera Z=±1000, X=100, Y=±100 and backward orientation preserved the stationary normal pose and complete native inventory. See [experiments.md](experiments.md) for exact snapshots and coverage.

## Manual player positioning for experiments

A player teleport enables the separate **Hold player** control. The addon holds the requested world position when the original `Level::update` queries `Room::getProgress`: before normal movement and immediately after rail movement, before the streaming predicates. It reports zero rail speed for this stationary manual pose. The native room loader, obstacle updates, destruction logic, origin rebasing and real audio clock continue to run on permitted updates. Every suppressed movement is logged as `rail_motion_suppressed`; snapshots expose `progression_held`, the held world pose, native phase and smoothed length.

This is an explicit developer intervention, not a claim that the shipped game supports arbitrary persistent player teleports. It is needed to apply a controlled independent variable to streaming. Camera-only movement never enables this hold. Turning Hold player off or exiting developer mode releases it; the original clock can then move the player back toward its rail target. Use Rebuild level to return to a clean run after destructive streaming experiments. Teleport automation accepts `raw:true` to reproduce the unmodified rail's response to a position-only write.

## Legacy research control modes

| Preset | Controlled target | Native world |
| --- | --- | --- |
| Pause & inspect | Independent camera | Paused |
| Fly camera · world running | Independent camera; normal player progresses | Running |
| Fly player · world running | Actual Level player pose and following view | Running |
| Watch original camera / transition | Original camera animation | Running |
| Play normally / leave tools | Original game input and camera | Running, subject to original pause/tutorial screens |

The older **Run world / Pause world** UI changed simulation state without changing the selected target. A paused player-flight target does not move; select Pause & inspect if camera-only movement is desired. Advanced controls retain independent free-camera and player-hold switches for experiments. Menu camera movement and transition capture use the same independent camera but no fictional menu Player entity. See [menu_and_transitions.md](menu_and_transitions.md).

The new world gate surrounds Game::update, including Level/Scene/Menu/Display updates. Native drawing continues. The outer audio clock and platform/UI callbacks are not frozen by this gate. The UI names the controlled target and world state explicitly, and native pause/tutorial state remains separately observable.

## Current Play/Edit control ownership

The current [Play/Edit interface](simple_play.md) moves the actual Level pose using native simulation dt and independently rotates its attached view. Rails adds the selected forward/backward rate; Free move uses manual input; Stop zeros movement while physics and shooting continue. Drawing supplies the separate camera pose temporarily, and original input receives that same pose/projection only while interpreting a shot. The original camera function remains available for original-controls runs.

Tools/Edit freeze Game updates and retain the player's position and gameplay view. Flying the detached editor camera changes neither. Resume restores that view and advances only on executed native updates, without matching the accumulated music-clock error. Resume during a menu transition finishes the native animated camera before attaching automatic Play controls. The legacy modes above are retained for research and can intentionally have different time/progression behavior.
