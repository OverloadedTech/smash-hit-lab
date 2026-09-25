# Automatic resume: process state and disk quick-save

**CONFIRMED (native code):** Smash Hit has an automatic room quick-save separate from the checkpoint choices exposed in the main menu. This explains why resume can be more precise than selecting a menu checkpoint. Whether an exact in-room pose survives also depends on whether Android kept the original process alive.

For permanent progress, checkpoint inventory, settings, cloud sync and anti-tampering checks, see [saves and integrity](saves_and_integrity.md).

## Disk representation

The native Player writes `user://quicksave.dat`. A populated file is obfuscated XML with these attributes:

| Attribute | Observed role |
| --- | --- |
| version | Written as 1.5.14 and checked by quickLoad |
| room | Current native room/progression index |
| timestamp | Time recorded when the file was written |
| score | Player score/progress value |
| balls | Remaining ball resource |
| streak | Current streak value |
| quicksavetimestamp | Additional timestamp restored into Player |

There is no XYZ camera/player pose, velocity array, full entity list, shattered-glass geometry, body transform snapshot or complete room-generator state in this serialization. The ordinary profile save is a separate facility; quickSave also invokes Player's normal save path.

`Level::enterRoom` schedules quickSave three updates later in an eligible normal campaign run. It clears quick-save for the inspected standalone/debug and locked-camera preview branches. Player::quickSave also skips Zen and the inspected newer-level campaign branch. These are version-specific control-flow observations, not assertions about every release of the game.

`Game::loadIncremental` calls Player::quickLoad during startup. If loading succeeds, it invokes `StartLevelAndBypassMenu("quickload", "resume")`; the native Level path rebuilds the room using restored Player fields. This is distinct from loading a menu checkpoint and its checkpoint inventory.

The encoding adds a repeating local key byte and the file length modulo 256 to each XML byte. `tools/read_save.py` reverses this using the key extracted from the supplied local APK; it never writes a save and contains no copied key. A cleared quick-save may be a plain empty XML element. File format and observed loader checks are documented without distributing the game's save data or key.

```bash
adb exec-out run-as com.mediocre.smashhit.dev cat files/quicksave.dat > build/quicksave.dat
python tools/read_save.py build/quicksave.dat
```

## Controlled reopening experiment

The experiment enters native room 1, waits for the original scheduled save, then changes the player pose, ball count and a real box after that save. It records the disk file without modifying it. It then compares:

1. **Home and reopen:** same Android process, with a developer freeze to hold the exact comparison state. Compare actual pose, room identity, ball count and edited geometry.
2. **Force-stop and reopen:** actual process death and a new PID. Observe the native quick-load result before enabling tools; compare room index, in-room progress, inventory and whether the geometry edit survives.

The resulting measurements are in `experiments/phase2/resume_summary.json` and [phase2_experiments.md](phase2_experiments.md). The distinction must be based on process identity and state, not on how similar the resumed screen looks. A warm reopen can preserve an existing world; a cold reopen has to reconstruct one. There is no claim that this addon persists developer camera settings or runtime geometry edits in the original quick-save.

## Measured result

**CONFIRMED (runtime):** the repeat experiment passed on APK `ea95c6d995c79caad3bdc08291a23f42569d66a26c5f5a66ceaa5a05630955f5`, with warm PID 4286 and cold PID 4696.

| State | Home / reopen, same process | Force-stop / reopen, new process |
| --- | --- | --- |
| Native room | Same room-1 instance | Newly generated room 1 |
| Player XYZ | Preserved `(13,8,-230)` | Reset to `(0,1,0)` in the new run's coordinates |
| Distance inside room | Preserved 70 | Returned to entrance, 0 |
| Balls | Preserved 15, including post-save damage | Restored 25 from the automatic save |
| Edited source box | Same edited mesh checksum | Original mesh rebuilt; edit absent |

The original quickLoad event restored the serialized score 340. `Level::reset` then initialized displayed distance by summing the preceding RoomDef display-length values, giving 272 for this room entrance. `Level::update` copied that value into Player's score. The score is therefore not an independent guarantee of restoring exact in-room distance. There is no evidence here of a generic percentage penalty; the observed change follows room reconstruction and displayed-distance calculation.

The first experiment failed an assertion that post-rebuild score must equal serialized score. That failure and its snapshots remain in `experiments/phase2/preliminary/resume_score_recomputed/`. The corrected test verifies the actual loader event and the later recalculation separately, without editing the file.

For this tested campaign path, an exact-looking return can be the still-alive process retaining its world. After actual process death, disk quick-save resumes the saved room rather than the precise world state. This can be finer than the checkpoints offered in the menu. Other modes and Android lifecycle outcomes need their own measurements; merely swiping away an activity does not always prove its process died.

## Developer-side saves

The Play/Edit addon now saves supported source transforms separately in `files/shdev/level-edits.json`, and view/movement preferences in `controls.json`. These versioned JSON sidecars use validation and atomic replacement. They do not extend the game's original `quicksave.dat` format or constitute a full simulation save. Static boxes and stable authored bodies can be reapplied after a cold restart; transient bodies and script/physics history are not serialized. See [Play/Edit persistence](simple_play.md). The quick-save observations above describe the original game's serializer.
