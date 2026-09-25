# Third-party material

`vendor/json.hpp` is nlohmann/json 3.11.3, downloaded from the upstream release's single-header include. Its full MIT license and copyright notices are retained in the header. The addon statically links the Android NDK's libc++ runtime under its distributed license.

Original game binaries/assets belong to their respective authors and are required as local input; this project does not claim authorship of them. Downloaded SDK/JDK/Ghidra/apktool/JADX/Frida components remain under their respective licenses. They are tooling dependencies, not recreated game source.

The desktop editor uses Three.js 0.169.0 under the MIT license. `tools/setup_desktop.py` downloads the required files from the pinned npm archive, verifies SHA-256 and retains its LICENSE. Those downloaded files are excluded from the source-only export and reproducibly fetched during setup. Python dependencies include NumPy (BSD), Pillow (HPND) and pyelftools (public domain); consult their installed distributions for complete notices.

The sibling Granny Smith and PinOut builders use **Dobby**, Apache License 2.0, from
`https://github.com/jmpews/Dobby`, commit
`e9fe7fbecae47a2287e761080f8b1133cc22e8fa`. `tools/setup_hook.py` (retained
here as shared tooling) verifies
archive SHA-256 `b5dddb530ae3b1abe8b61dd3a690eaf0ffe74900b0313c3d1bee0597691cf2d3`
before extracting it. Its source and build output remain downloaded local
dependencies; the sibling builders include its full LICENSE in each new Lab
APK as `assets/lab/Dobby-LICENSE.txt`. The Smash Hit addon build
(`tools/build_debug.py`) does not link Dobby; it uses verified relocation
hooks into the original library instead.

The bootstrap applies two local changes to that pinned source: it makes the
header-defined logger/accessor C++ inline entities to resolve duplicate
definitions, and explicitly initializes `InterceptEntry::thumb_mode` to false
before checking for Thumb targets. The latter fixes a measured ARM32
wrong-instruction-mode hook crash; see the notebook. These patches are project
modifications, not claims about an unmodified upstream release. The addon
also validates ARM/Thumb entry and trampoline mode agreement.
