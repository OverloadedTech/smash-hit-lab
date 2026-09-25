# Contributing

This is an unofficial fan research project. We investigate the compiled
game, identify formats and runtime behavior, add isolated instrumentation,
and test explanations against the running game.

## Scope

- This repository contains **research tooling only**. No game source,
  assets, or APKs are committed here.
- Each user must supply their own compatible game APK locally.
- All findings are labeled **CONFIRMED**, **LIKELY**, **HYPOTHESIS**,
  or **UNKNOWN** in the research notebook.

## How to contribute

1. **Report findings** with evidence: file paths, hashes, runtime
   measurements, and APK/process identity.
2. **Preserve failures**: keep failed experiments and their evidence in the
   record instead of replacing them with unverified assumptions.
3. **Verify against the source**: every claim should trace to a
   specific artifact, disassembly, or named runtime experiment.
4. **Do not commit** game binaries, assets, decompilation output,
   saves, or signing keys.

## Development

See `README.md` and `docs/public_repository.md` for setup instructions.

Run `python3 tools/check_source.py --javascript` with Python 3.11.8+, Node.js
22, Git, Bash and g++. See [verification scope](docs/VERIFICATION.md) for
device/browser dependencies. Report exactly which checks ran and which did
not; source checks alone do not validate Android runtime behavior.

## License

All tooling and research notes are MIT-licensed. See `LICENSE`.

## Conduct

Issues, pull requests and discussions follow the [code of conduct](CODE_OF_CONDUCT.md).
