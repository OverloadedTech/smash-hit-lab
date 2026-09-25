# Verification scope

This repository is an experimental source release. Historical runtime
reports describe their named APKs and environments; their PASS labels do not
certify a newly built APK or a different device.

## Source-only checks

From the repository root, with Python 3.11.8+, Git, Bash and a C++20-capable
`g++` installed:

```bash
python3 tools/check_source.py
```

For the full CI check, also install Node.js 22 and run:

```bash
python3 tools/check_source.py --javascript
```

The checker validates Python syntax (including experiments), shell syntax,
local Markdown link targets, excluded-file rules and private-output ignore
fixtures. It compiles and runs the existing native diagnostic-log test for
rotation, restart, oversized records and filesystem errors. The JavaScript
flag checks syntax in browser modules and probes, without executing them.
Failures return a nonzero status. No APK or Python package install is needed.

These checks do not compile the complete Android addon, validate native hook
offsets, execute the browser UI or establish runtime feature correctness.

## APK and device checks

The [README](../README.md) gives the supported input and build commands. A
fresh APK build, installation, cold start and native/UI regression run still
require that APK, the downloaded Android toolchain and a compatible device or
emulator. Those checks are not part of source-only CI.

[Play/Edit experiments](simple_play_experiments.md) describes the historical
procedures. Browser experiments additionally need
`python -m pip install -r requirements-test.txt` and Chromium; existing
harnesses use `/usr/bin/chromium`. Legacy Frida probes need a compatible
Frida client/server installed separately. Review each harness's device,
package and reset options before running it.

When reporting a new runtime result, include the source revision or hashes,
input/output APK hashes, ABI, Android version, device identity, commands and
actual results. Record failed and unrun checks as such. ARM64 hardware
coverage remains unverified in the supplied historical reports.
