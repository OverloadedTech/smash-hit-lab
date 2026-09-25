# Menu and transition exploration

**CONFIRMED, native code and corrected runtime experiment:** the homepage includes scripted 3D scene content plus 2D interface elements. It is not a gameplay room with the usual Level object collection. The addon can move the main view used by `Display::enterMenuMode`, so you can leave the menu's intended view and inspect it from arbitrary positions. Screen-space UI remains screen-space; menu images/canvases do not become editable gameplay colliders.

The normal menu rotation comes from `Menu::update` and `Display::update`. `Game+0x258` points to Menu; its eased transition amount is at Menu+0x420. An amount near 1 is the menu end and near 0 is gameplay. Display derives translation, yaw and roll from that amount. The normal renderer and transition remain intact.

Tap **Tools → Explore menu** on the homepage. This freezes world updates and detaches the camera. Use the stick, UP/DOWN, drag-to-look, speed, and camera teleport just as during gameplay. There is no active player to fly in an empty menu; use camera controls there.

The optional **Position, rooms & research details** dialog provides **Capture transition into game / to menu**. These invoke the verified Classic start/return paths, let the rotation reach its midpoint, freeze it and enter the independent Explore view. **Resume** finishes the original animated camera transition; automatic Play controls attach only when its gameplay endpoint is reached. The helper starts Classic checkpoint 0; it is not a selector for every game mode or newer campaign.

The Classic menu's start command calls `Game::RestartLevel("0")`. `Game::StartNewLevel` is a different campaign path in this APK; an early pilot using it produced an invalid room and was discarded. The developer helper matches the verified Classic path.

## Freeze integration

Freezing only `Level::update` cannot stop the menu. The addon now gates `Game::update`, which includes level simulation, Scene ticks, Menu updates and Display updates. It still renders frames and allows independent camera movement. Music, platform callbacks and some frame-level interface fades are outside this simulation gate. The visible menu camera rotation, level physics and level scripts stop.

`Game::frame` contains an unusual startup correction: after its second update slot it subtracts one native tick while tick<12. Skipping updates without accounting for this drove a pilot process to tick -4,585, leaving the loading logo visible. The corrected gate preserves the last executed update's tick only when a skipped slot would cause that decrement. Normal frames retain the original behavior. This code path was checked in both 64-bit libraries.

On the corrected x86_64 build, the full homepage showed the normal `(50,4,0)` view after startup. Camera teleport to `(62,12,-10)` left the player and native update count unchanged. The game transition froze at approximately 0.490 and the return transition around its midpoint; the camera moved while the amount and update count stayed fixed. See [second-phase experiments](phase2_experiments.md) and `experiments/phase2/menu_*.json`.
