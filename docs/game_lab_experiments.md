# Three-game release verification

The existing Smash Hit Play/Edit APK is preserved. Granny Smith and PinOut
have separate embedded addons that operate on their actual native engines.
An APK counts as verified only when its own source identity and full APK
hash match the completed experiment reports. A partial report is not a pass.

## Runtime scope

| Game | Runtime environment | Included APK architectures |
| --- | --- | --- |
| Smash Hit | Android 11 / API 30, x86_64, software graphics | ARM64, x86_64 |
| Granny Smith | Android 6 / API 23, ARMv7, software CPU and graphics | ARMv7, ARM64 |
| PinOut | Android 8 / API 26, x86_64, software CPU and graphics | ARM64, x86_64 |

**CONFIRMED limitation:** No physical ARM64 device was available. ARM64 layouts
are separately mapped and compiled; an emulator result for another ABI does
not prove compatibility with a particular phone/GPU. Original platform billing,
cloud services and every campaign object are outside these local checks.

PinOut's API 26 emulator displayed SystemUI/keyguard ANRs at a clean boot
before the game started. Its SystemUI package was disabled for the subsequent
test setup and the emulator rebooted. This is an environment intervention,
not an APK requirement. The application still uses Android's real View/input
dispatch, the original game renderer and original physics. Earlier API 30
attempts also suffered system-server restarts; those failures are retained.

## What the checks establish

- **Native engine:** pause gates actual gameplay/physics while render frames
  continue; six camera directions, looking behind and camera teleport leave
  the player independent. Selection uses actual render triangles. Translation,
  supported scale and rotation change native body/render data, with independent
  original collision queries. Group undo and saved edits survive native reload
  and process death. Original simulation resumes afterward.
- **Android touch:** a separate shell test helper injects real InputManager
  events. The experiment waits for visible controls and reads their actual
  screen bounds. A world drag changes native geometry, creates one undo step,
  and can be undone/redone and saved using visible buttons. Look gestures leave
  the player fixed; FOV changes are checked against native rendered screenshots.
  The helper is not bundled in the APK or needed for normal use.
- **Desktop:** Chromium mouse events drag the rendered transform handle.
  Applying changes the native body; Undo restores it. A two-body operation is
  applied/saved. Stale process/scene identities are rejected. The checks also
  record JavaScript errors and source fingerprints.
- **Granny Smith player:** fourteen additional checks cover far forward,
  backward and downward travel, actual Box2D integration speed, restored
  collision, live input after reload and an authored death sensor. The same
  sensor is tested with immortality enabled and disabled.
- **PinOut loading:** the packaged adapter drives the original table loader
  for forward/backward jumps and last-table access. The separate original-game
  streaming experiment covers sixteen controlled conditions, including fixed
  player/free-camera movement, retained caches and actual authored-body deload.

**CONFIRMED (completed release checks):**

| Game | Native | Android touch | Desktop | Extra player study | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Granny Smith | 31 | 11 | 12 | 14 | 68 |
| PinOut | 34 | 11 | 12 | - | 57 |
| Smash Hit | Combined Play/Edit suites | Included | Included | Included | 72 |

Smash Hit also retains its bounded logger checks. These are assertion counts,
not a claim of exhaustive level or device coverage. The separate original
PinOut streaming study's sixteen checks are not added to the packaged-addon
total. Reports are under `analysis/games/GAME/runtime/{native-release,
touch-release,desktop-release}/`; Granny Smith also has `player-release/`.

| Delivered APK | SHA-256 |
| --- | --- |
| `smash-hit-lab.apk` | `a02ecf9e92601b98b9c13cd569282e3f116bb0789b77c8c61a00c76fdc3824d1` |
| `granny-smith-lab.apk` | `da32e2958fdf54d382716dc89ef8927e5797b8f6c6e648b6a6237aa26bc54d54` |
| `pinout-lab.apk` | `d710881736765806d3d9766172e2f13b607964a17a8e66af33841d3430f88c57` |

The APK-bound aggregate is `artifacts/mediocre-labs-validation-report.json`.
It records all component report hashes, runtime scope and source identities.
The APK builder and packager compare retained original bytes: 814 asset/library
entries for Granny Smith and 1,449 for PinOut. Smash Hit's existing build report
records 2,433 retained entries.

## Reproduce

Use dedicated Lab installations: these commands reset the active run and clear
saved test overrides. The full integration suite also restarts the app.

```sh
source tools/env.sh
python experiments/verify_game_lab.py --game granny-smith --serial DEVICE \
  --port 18768 --out analysis/games/granny-smith/runtime/native-release --allow-reset
python experiments/verify_granny_player.py --serial DEVICE --port 18768 \
  --out analysis/games/granny-smith/runtime/player-release --allow-reset

# Run the appropriate desktop.game_server first; use port 8767 for PinOut.
python experiments/verify_native_desktop.py --game granny-smith --serial DEVICE \
  --port 18768 --url http://127.0.0.1:8766 \
  --out analysis/games/granny-smith/runtime/desktop-release --allow-reset
```

PinOut uses game `pinout`, native forwarding port `18767`, and the analogous
report paths. The native abstract sockets are `granny_smith_lab` and `pinout_lab`;
forward them with `adb -s DEVICE forward tcp:PORT localabstract:SOCKET`.
Browser experiments additionally need Playwright and a local Chromium binary.
Android touch fixtures use 160 dpi, 960×540 for Granny Smith and 540×960 for
PinOut. Start `tools/android_input.py` with the matching `ANDROID_SERIAL` and
`MEDIOCRE_INPUT_PORT`, then pass that port to `verify_game_lab_ui.py`.

`tools/package_labs.py` checks completed native/touch/desktop reports against
the exact APK and current sources, checks retained original assets/libraries,
and assembles `artifacts/releases/mediocre-labs/`. It refuses incomplete or
stale evidence. `tools/audit_public_research.py` separately checks the staged
source-only export, archive and private release manifest.

## Failed attempts and corrected assumptions

The notebook preserves failed external debuggers, the ARM/Thumb dependency
defect, Granny Smith's omitted native stop lifecycle, replay/spawn overrides,
PinOut's paused streaming initialization and Android system failures. None is
retroactively called a passing test.

An unpaged Android panel and repeated parsing of full snapshots caused heavy
layout/GC work in a PinOut ANR trace. The current panels use twelve-row pages
and search. Live status uses a compact cached snapshot; full research data
remains available on demand and through the desktop/socket interface.

The first touch fixture assumed that a native mode acknowledgment meant the
new Android panel had already completed layout. A Close tap could consequently
reach the world while the panel was still being placed. The retained screenshot
and native undo history exposed that race. The revised fixture waits for actual
visible controls and confirms that the panel is gone before a world drag.
