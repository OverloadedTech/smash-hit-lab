# Saves, cloud sync and integrity checks

Scope: the supplied Android 1.5.14 APK. **CONFIRMED (static)** means the original native or managed control flow was inspected. **CONFIRMED (captured data)** means a file was copied read-only from the Lab emulator. The earlier warm/cold reopening experiment is separate runtime evidence. No edited save was installed, entitlement changed, or cloud request issued for this investigation.

## Files and responsibilities

The engine resolves `user://` to the app's private files directory. The usual Android path for the original package is `/data/user/0/com.mediocre.smashhit/files/`; Lab uses `com.mediocre.smashhit.dev` and separate data. Files need not all exist before their corresponding feature writes them.

| File | Representation | Stored information | Evidence |
| --- | --- | --- | --- |
| `progression.xml` | Obfuscated XML, root `smashhit` | Profile identity/metadata, records, statistics, selected mode and checkpoint inventory | Native writer/loader; captured 1,170-byte file |
| `quicksave.dat` | Obfuscated XML, root `quicksave`; a cleared file can be plain `<quicksave/>` | Automatic room resume and ball/streak inventory | Native writer/loader, captured file, controlled reopening |
| `config.xml` | Plain XML, root `config`, with an `audio` child | Game configuration/property values, including graphics, locale and music/sound toggles | Native writer/loader; absent in this particular capture |
| `achievements.xml` | Plain XML | Achievement `id`, `count`, `reported`, `isdirty` | Native writer/loader; captured empty achievements document |
| `tutorials.json` | Plain JSON | `completedTutorials` IDs; the captured document is an array containing that object | Native model/manager; captured file |
| `key.dat` | Obfuscated local entitlement token, not XML | Cached purchased-premium check | Native writer/loader; no token created or modified |

**CONFIRMED (captured data):** Android/Firebase SDK files and a separate `xpromomodel.json` also exist. They are not a serialized level. This investigation does not enumerate every SDK cache, analytics database or backup policy.

## Permanent progression

**CONFIRMED (static and captured data):** root attributes include `uid`, `highscore`, `highscoreT`, `highscoreE`, `highscoreC`, `playtime`, `startcount`, `mode`, `version`, `platform`, `model`, `laststats` and `installdate`. `uid` is initialized from a native random value; it must not be described as a Google account ID or hardware identifier. The registered property set also includes rating/ad bookkeeping fields. Which fields appear depends on values and the property's serialization flags. A `premium` metadata attribute can also be emitted; the entitlement loader separately resets and checks its actual entitlement flag.

The serializer writes these statistics groups:

| XML group | Internal mode |
| --- | --- |
| `stats` | Normal / Classic |
| `statsT` | Training |
| `statsE` | Expert |
| `statsC` | Co-op |

Their registered fields are `balls`, `peakballs`, `ballshit`, `obstacles`, `obstaclescleared`, `powerups`, `powerupstaken`, `distance`, `streak`, `score`, `broken`, `accstreak`, `accballs`, `accdistance` and `rooms`. These are statistics, not an active entity list; for example, `stats.balls` is not the current quick-save ball inventory. Exact aggregation semantics of every counter are outside this investigation.

Checkpoint entries use `checkpoint`, `checkpointT` or `checkpointE`, with `index`, `balls` and `streak`. The inspected arrays have 13 slots; normal report/load operations handle checkpoint indices 1–12, and the default start supplies 25 balls and streak zero. `reportCheckpoint` retains the maximum ball count and maximum streak independently. The profile loader also merges checkpoint values by maxima. A checkpoint record therefore need not be the inventory from the most recent attempt, or even two values captured together in one attempt. This is native control-flow evidence, not a new edited-save experiment.

**CONFIRMED (static):** `Player::save(bool)` updates records/statistics, serializes the profile, writes it, and saves achievements. Eligible room quick-save invokes it with cloud saving disabled; leaving ordinary gameplay invokes it with cloud saving allowed. The Android pause callback inspected here disables audio; it does not write a complete in-room world snapshot.

**CONFIRMED (static and runtime toggle experiment):** the Lab's **Unlock all levels · this session** overrides the checkpoint availability/read path, without filling the stored ball/streak arrays or setting the premium flag. The original `Player::save(QiOutputStream&)` walks the stored checkpoint arrays directly; it does not call the overridden `Player::getHighScore(index)` to obtain checkpoint availability. Merely displaying unlocked levels therefore does not serialize every displayed checkpoint as a new 25-ball record. The on/off experiment also observed unchanged original checkpoint records. Ordinary gameplay after jumping can still report checkpoints and save progress in the separate Lab package. This is not a claim that an entire unlocked play session leaves Lab save files unchanged. See [travel tools](travel_tools.md).

## Automatic resume

**CONFIRMED:** quick-save has exactly these emitted attributes: `version`, `room`, `timestamp`, `score`, `balls`, `streak`, `quicksavetimestamp`. Eligible campaign room entry schedules it three updates later. Game-over clears it. Zen and the inspected newer-level campaign branch skip this quick-save path.

It contains no player/camera XYZ, rotations, velocities, ball trajectories, broken-glass mesh state, complete room-generator state or developer edits. Cold startup loads the saved room and reconstructs it. Warm reopening can retain the existing world because the original process is still alive.

In the earlier controlled experiment, Home/reopen retained position `(13,8,-230)`, 15 balls and an edited box in the same process. Force-stop/reopen created a new process, rebuilt the saved room at its entrance, restored the 25 balls on disk, and lost the runtime geometry edit. See [automatic resume](quick_resume.md) for the score recalculation and complete evidence.

## Encoding and local validation

**CONFIRMED (static):** profile and populated quick-save files use the same additive byte transformation. If `P` is the serialized byte array, `K` the repeating key embedded in this native library, and `N` the byte length:

```text
encoded[i] = (P[i] + K[i mod key_length] + N) mod 256
decoded[i] = (encoded[i] - K[i mod key_length] - N) mod 256
```

The native functions are named `encrypt`/`decrypt`, but this is reversible obfuscation. There is no random nonce, per-save secret, MAC or digital signature in these inspected save transformations. The length contributes only its low byte; it is not an authenticated checksum. The research reader obtains the key from the user's supplied APK rather than containing a copied key.

**CONFIRMED (static):** `Player::load()` first decodes `progression.xml`. If its XML/profile load fails, it reverses that transformation, rewinds the stream and tries the original bytes as plaintext. The profile parser requires a valid native XML document rooted at `smashhit`, converts fields, constrains the mode and bounds checkpoint indices. It does not verify a save signature or compare the profile's version against a cryptographic authority.

`Player::quickLoad()` requires a `quicksave` root and version exactly `1.5.14`, then restores the numeric room, score, balls, streak and quick-save timestamp. It does not authenticate those values. Its inspected body does not use the separate `timestamp` attribute as an expiration or rollback check. Other gameplay code can still interpret or recompute loaded values; the observed score recalculation is one example. A cleared plain `<quicksave/>` is not an accepted populated resume.

**CONFIRMED (static):** the resource writer opens the destination with `fopen(..., "wb")` and writes the buffer. No temporary-file/rename transaction or rotating backup is visible in this native path. Interrupted-write recovery has not been experimentally tested.

## Native XML quirk and read-only tooling

**CONFIRMED (captured data):** the captured original-writer profile repeats `version`, `platform` and `laststats` on its root. Both occurrences have identical values in this file. Standard XML parsers reject duplicate attributes; that failure is not evidence of a damaged or tampered save.

The native writer first writes PropertyBag values, then explicitly emits metadata again. `QiXmlWriter::setAttribute` appends an attribute. Named native parser lookup returns the first match, while PropertyBag loading iterates attributes and assigns values. Conflicting duplicate values should not be silently collapsed into a guessed universal interpretation; no conflicting-duplicate runtime test was performed.

The reader now provides an exact-byte option:

```bash
source tools/env.sh
python tools/read_save.py path/to/progression.xml --raw
python tools/read_save.py path/to/quicksave.dat
```

`--raw` preserves the decoded document, including duplicates. Default JSON output remains strict and reports an actionable error instead of repairing malformed XML. Both modes are read-only. Captured-file tests verify exact output, the previous quick-save API, duplicate rejection and unchanged input hashes. Raw saves, identifiers and decoded evidence remain local and are excluded from the public source export.

## Cloud saves

**CONFIRMED (static):** the native cloud path serializes the progression profile, applies the same obfuscation, compresses the result through `QiCompress`, and transfers it across the native/Java bridge as hex. Java converts that hex back to bytes and stores a Google Play Games snapshot named `smashhit.bin`, with description `Smash Hit auto save`.

The managed code opens snapshots with `RESOLUTION_POLICY_MOST_RECENTLY_MODIFIED` (3). On download, native `Player::tick` obtains the data, decompresses and decodes it, and calls the merge form of the profile loader before saving again. Checkpoint maxima are one part of that merge. This path does not upload the active world's bodies or an exact in-room camera pose.

Native cloud calls are gated by premium-related flags; the Android layer also requires Google Play Games sign-in. **UNKNOWN:** current server acceptance, cross-device outcomes, unresolved conflict behavior, and cloud operation under Lab's different package/signature. Inspecting the client does not reveal every server-side check.

## Anti-tampering: separate mechanisms

| Mechanism | Finding |
| --- | --- |
| Local progress authenticity | **CONFIRMED (inspected code):** no MAC or digital signature protects the profile/quick-save fields. Obfuscation and parser checks are present. |
| Save compatibility/sanity | **CONFIRMED:** root checks, an exact quick-save version check, numeric conversions, mode/index bounds and record merging. These do not prove a score was earned. |
| Premium cache | **CONFIRMED (static):** `key.dat` is compared against a deterministic obfuscated token derived from the device model, local profile `uid` and fixed native data. This is a separate entitlement check, not an integrity hash of all progress. No token is generated by the research tools. |
| Purchase ownership | **CONFIRMED (managed code):** Google Play Billing queries purchases, checks purchase state/product IDs and acknowledges purchases, then updates native ownership through the bridge. Live service validation was not tested. |
| File access | **CONFIRMED (Lab capture):** private files are owned by the app UID with owner-only permissions. Android's sandbox limits ordinary cross-app reads/writes; Lab's debuggable `run-as` access is not evidence that the original release permits it. |
| APK signature | Android verifies package signing at install/update. The separately signed Lab package working does not imply it can update the original package or use its authenticated services. APK signing is distinct from authenticating save contents. |
| Dedicated gameplay anti-cheat / anti-debug | **NOT FOUND in the inspected game-owned Java and native save/gameplay paths.** Local modifications run in the tested emulator. This is not a proof that every bundled SDK, release, mode or remote service lacks integrity checks. |

Local progress is largely trusted after parsing. We have established the format and inspected its validation, but have not established that every modified value would survive later game logic, cloud merging or remote leaderboard checks.

## Local evidence

- `analysis/decompiled/save/`: original `Player::save` and `Player::load` overloads.
- `analysis/decompiled/saves_x86_64/`: profile construction, checkpoint operations, byte transformations, cloud path, achievements and file writing.
- `analysis/decompiled/save_xml_x86_64/`: XML behavior, tutorial persistence and audio configuration.
- `analysis/decompiled/phase2_x86_64/`: quick-save/load and game-over paths.
- `analysis/jadx/sources/com/mediocre/smashhit/`: `CloudSave`, `GooglePlaySystem`, `AndroidStore`, `PurchaseSynchronizer`.
- `experiments/save_analysis/captured_files.json` and `reader_validation.json`: read-only capture metadata and reader checks. No live save-tampering test is claimed.

## Developer-side saves

The Play/Edit addon now saves supported source transforms separately in `files/shdev/level-edits.json`, and view/movement preferences in `controls.json`. These versioned JSON sidecars use validation and atomic replacement. They do not extend the game's original `quicksave.dat` format or constitute a full simulation save. Static boxes and stable authored bodies can be reapplied after a cold restart; transient bodies and script/physics history are not serialized. See [Play/Edit persistence](simple_play.md). The quick-save observations above describe the original game's serializer.
