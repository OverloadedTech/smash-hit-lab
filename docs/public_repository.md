# Source repository

This is the standalone Smash Hit Lab source export. Use the
[README](../README.md) for the APK hash, input path, toolchain setup, build
command and desktop entry point. Shared notes also describe Granny Smith and
PinOut; see [the documentation index](README.md).

Original tooling and notes are [MIT-licensed](../LICENSE). Dependencies keep
their [own notices](../dev/THIRD_PARTY.md). Game APKs, native game libraries,
extracted assets, saves, scene exports and signing keys are local inputs or
outputs. They are not distributed with this repository.

The notebook records historical experiments. Raw files under `analysis/`,
`artifacts/` and experiment result directories are omitted. A reference to
one of these files does not mean it is available in this checkout. Some
references name documentation that was omitted as well.

`tools/export_research.py` exports a source allowlist with file hashes.
`package_game_repos.py`, `package_labs.py`, `summarize_game_repos.py` and
`audit_public_research.py` are inherited workspace/release procedures. They
require the original multi-game workspace and private evidence, and are not
the build or verification entry points for this standalone checkout.

See [verification scope](VERIFICATION.md) for checks that can run here.
