# Desktop editing for Granny Smith and PinOut

This browser editor reads actual geometry from the running Android Lab and
applies transforms to its native bodies. The game continues to provide its
renderer, physics and scripts. This is separate from the deferred native
Windows/Linux game port and from Smash Hit's
[source-segment desktop editor](desktop_editor.md).

## Connect

Install a current Granny Smith Lab or PinOut Lab APK, start a level/run, and
connect the device with USB debugging. `adb devices` must list it as authorized.
The addon itself needs no root. Use Python 3.11+ and a WebGL browser:

```sh
python -m pip install -r desktop/requirements.txt
python tools/setup_desktop.py
# Substitute the serial from adb devices.
python -m desktop.game_server --game granny-smith --serial DEVICE_SERIAL --port 8766
# Or, in another terminal:
python -m desktop.game_server --game pinout --serial DEVICE_SERIAL --port 8767
```

Open **http://127.0.0.1:8766** for Granny Smith or
**http://127.0.0.1:8767** for PinOut. Click **Read scene from game · pause**. The server
pauses the native world, asks the addon to export its current objects and
loads their real render triangles. Exporting can take time on a software
emulator. Starting the server alone does not change the game.

The page supports both live and local-file workflows. **Open scene** reads a
previously exported scene JSON; **Save scene file** saves the current browser
project. A saved project contains game geometry, so keep it outside the
public research repository.

The private three-game release includes `data/GAME/sample-native-scene.json`
for each new Lab. To inspect one without a device, start the server with
`--game GAME` and omit `--serial`, then choose **Open scene**. ADB is used only
when connecting/applying to a game. A sample's old process identity cannot be
used to apply it to a newly started native scene.

## Edit

Click geometry or choose an entry in the object list. Search filters the real
name, type, object key and level/table. Ctrl/Shift-click or **Add to selection**
adds objects. **Select all** selects the loaded project.

Use **Move / Rotate / Scale** and drag the colored transform handles. The
operation changes a selected group around its center. XYZ step buttons offer
small repeatable translations. Single-object fields accept position, rotation
and scale; group fields translate the center. **Undo / Redo** restore whole
operations. **Focus** centers the view.

Right-drag orbits, middle-drag pans, and the wheel zooms. The desktop FOV
slider changes the browser view's vertical FOV; the Android Lab has its own
horizontal FOV control.

**Apply selected to game** sends the chosen poses to the current native scene.
**Apply + save for next run** also stores them through the addon's saved
override system. Native collision and render data follow the same validated
edit path as touch editing. The world stays paused for inspection; press
**Play** in the Android Lab to resume.

The sidebar shows actual native properties and loading metadata. Mesh colors
are editor aids; the page does not reproduce original textures, fog, lighting,
animations or physics. Granny Smith scaling is disabled for bodies that the
native adapter reports as unsupported.

## Scene identity and safety against stale edits

A live project records the game, original library SHA-256, process ID and
native scene generation. Apply checks all four before changing native memory.
If the app restarted, a level loaded or mesh resources were replaced, reconnect
and work on the new export. Merely retaining a stale pointer or an old browser
tab cannot authorize applying to a different scene.

Saved native overrides survive app restarts independently of the desktop
connection. Loading an old scene JSON is useful for offline inspection; it
does not automatically rebind that project to a different live process.

The server listens only on `127.0.0.1`, checks request host/origin, limits body
size and uses ADB `run-as` to access the separate debuggable Lab package.
Disconnecting the browser leaves the game in its current paused state.
It does not silently resume physics while someone is editing.

Source: [desktop/game_server.py](../desktop/game_server.py),
[desktop/game_web/](../desktop/game_web/), and the native scene/edit commands
in `labs/common/native/editor.cpp`, which is part of the game Lab sources
rather than this repository.
