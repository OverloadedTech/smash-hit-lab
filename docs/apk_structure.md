# APK structure

**CONFIRMED**, supplied build: package `com.mediocre.smashhit`, version 1.5.14 / 1051400, minimum Android API 26, target API 35. Launcher: `com.mediocre.smashhit.MainActivity`. Requires OpenGL ES 2.0 and multitouch. Input hash is recorded in the notebook.

The APK has 3,500 entries and is 94,008,797 bytes. See `analysis/reports/apk_inventory.json` for the complete inventory and `manifest.json` / `AndroidManifest.xml` for manifest evidence.

| Part | Observed role |
| --- | --- |
| `classes.dex`, `classes2.dex`, `classes3.dex` | Android lifecycle, Google/Firebase/AndroidX SDKs, game platform integration |
| `lib/{arm64-v8a,armeabi-v7a,x86,x86_64}/libsmashhit.so` | C++ engine, gameplay, Lua, rendering, physics, audio |
| Crashlytics libraries, datastore counter per ABI | Platform diagnostics and persistence support |
| `resources.arsc`, `res/`, binary manifest | Standard compiled Android resources, SDK UI and configuration |
| `assets/` | 2,421 files, primarily game data |

Each original ABI directory contains `libsmashhit.so`, `libcrashlytics.so`, `libcrashlytics-common.so`, `libcrashlytics-handler.so`, `libcrashlytics-trampoline.so`, and `libdatastore_shared_counter.so`. The game/engine and its embedded libraries are in `libsmashhit.so`; the other five are Android SDK support libraries. The development package retains the original arm64/x86_64 copies and adds a separate `libshdev.so` and fourth DEX.

Most game asset filenames append `.mp3` to another extension. **CONFIRMED:** these are not MP3 files. `ResMan::load` appends the suffix when resolving appropriate logical resource names. Read content, not just the last extension.

| Logical asset | Count | Verified format |
| --- | ---: | --- |
| XML | 755 | Text XML, including 643 segments, 20 levels, 11 convex meshes, 74 UI documents |
| Segment mesh | 643 | Zlib-compressed binary vertex and triangle arrays |
| MTX texture | 522 | Custom wrapper; 15 JPEG payloads and 507 MTX JPEG-plus-alpha payloads |
| PNG | 99 | Standard PNG |
| OGG | 166 | Ogg containers, including music and sound |
| Lua | 157 | Text Lua source |
| GLSL | 37 | Combined vertex/fragment shader source |
| OBJ / MTL | 3 / 1 | Text model geometry and material declarations |
| FNT / UFNT | 9 / 18 | Text font metrics; UFNT includes Unicode-to-glyph mappings and atlas metrics |
| TXT | 9 | Localization |

`tools/analyze_assets.py` validates every segment mesh, XML document, full MTX JPEG/alpha payload, font metric file, and Vorbis identification packet. Its complete run found no parse/structural failures. Segment assets contain 40,062 boxes, 1,638 obstacle declarations, 1,112 decals, 59 powerups, six model declarations, and one water declaration. Mesh totals: 3,475,048 vertices and 1,737,524 triangles. These are asset totals, not simultaneous runtime object counts.

**CONFIRMED:** the APK ZIP and per-mesh zlib streams are the principal containers observed. No Unity/Unreal archive structures or external OBB references have been found in the game asset inventory. Absence of every possible embedded format is not claimed.
