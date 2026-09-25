# Smash Hit Lab

Unofficial research tools for **Smash Hit 1.5.14**: an Android Play/Edit addon,
native geometry and collision editing, camera and travel controls, format
analysis, and a desktop segment editor with optional live ADB integration.

This is an experimental source release. Supply your own compatible APK.
Game binaries and assets are not included.

This is a fan project. It is not affiliated with, endorsed by or connected to Mediocre AB, who publish Smash Hit. The game's name is used only to say which game the research is about, and it remains their trademark. See [LICENSING.md](LICENSING.md).

## Desktop editor

Use Python 3.11.8+ and a WebGL browser. Run from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r desktop/requirements.txt
python tools/setup_desktop.py
python -m desktop.server --apk /path/to/your/smash-hit.apk
```

Open http://127.0.0.1:8765. The editor reads segment geometry from the APK;
it does not simulate Lua scripts or game physics. Three.js is downloaded and
hash-checked during setup. See [desktop controls](docs/desktop_editor.md).

## Build and install the Android addon

Native build scripts target Linux x86_64. Place the original APK at
`com.smash.hit.apk` in the repository root. Its SHA-256 must be:

```text
3b2ffa02fee8ca762f40648f1a9bec5c308764e881dd6a79cacd6dccdb16e338
```

```bash
python3 -m venv tools/venv
tools/venv/bin/python -m pip install -r tools/requirements.txt
tools/venv/bin/python tools/bootstrap.py --components build
source tools/env.sh
python tools/prepare_input.py
python tools/build_debug.py
adb install -r artifacts/smash-hit-lab.apk
adb shell am start -n com.mediocre.smashhit.dev/com.mediocre.smashhit.MainActivity
```

The bootstrap downloads SDK, NDK, JDK and APK tooling, requiring several GB.
The addon installs as `com.mediocre.smashhit.dev`, alongside the original.
Keep the generated signing key under `build/` for compatible updates.

## Scope and verification

The addon targets x86_64 and ARM64. Historical runtime reports cover an API 30
x86_64 emulator; ARM64 was statically checked and compiled, not tested on a
physical device. These reports do not establish compatibility with every
Android version, GPU or game mode.

Start with [Play/Edit controls](docs/simple_play.md),
[engine overview](docs/engine_walkthrough.md), and
[known limits](docs/unknowns.md). The [notebook](REVERSE_ENGINEERING.md) preserves
the three-game research chronology. Its recorded results are not fresh test
results for this checkout. See [the documentation index](docs/README.md).

Run `python3 tools/check_source.py` for the source-only checks used by CI.
See [verification scope](docs/VERIFICATION.md) and [contributing](CONTRIBUTING.md).

## License

Original tooling and notes use the [MIT license](LICENSE).
[Third-party notices](dev/THIRD_PARTY.md) apply to dependencies. No license to
Smash Hit or its assets is granted; this project is unofficial.

Written by Luca Zani ([OverloadedTech](https://github.com/OverloadedTech)).
This repository is a standalone source export of the Smash Hit tooling from a
larger private research workspace covering three games, so its history starts
at the export rather than at the first day of the work. That workspace holds
the original APKs, decompiled game code, extracted assets and device captures,
none of which can be redistributed, so publishing its history was never an
option. The tools and the notebook are the part that can be shared.
