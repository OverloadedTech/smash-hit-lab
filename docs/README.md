# Documentation

Begin with [Play/Edit](simple_play.md), [developer mode](developer_mode.md),
[desktop editing](desktop_editor.md), [engine overview](engine_walkthrough.md)
and [verification scope](VERIFICATION.md).

The export retains shared research from the original multi-game workspace.
`mediocre_comparison.md`, `other_game_devkits.md`, `native_scene_editor.md`,
`game_lab_experiments.md` and the root notebook also discuss Granny Smith and
PinOut. Those adapters require their respective repositories; Smash Hit's
addon is under `dev/native/` and uses `tools/build_debug.py`.

Historical PASS/CONFIRMED labels refer to the builds named in their reports.
Raw evidence and some referenced pages were omitted during export, so a page
named here may be documentation that this checkout does not contain. The root
README has the current setup commands.

## Engine reference

Notes on how the game itself is put together, written from decompiled code and
from what the addon observes at runtime.

- [Architecture](architecture.md) and [APK structure](apk_structure.md)
- [Object system](object_system.md), [player](player.md) and
  [ball lifecycle](ball_lifecycle.md)
- [Physics](physics.md), [glass shattering](glass_shattering.md) and
  [rendering](rendering.md)
- [Camera](camera.md), [level streaming](level_streaming.md),
  [menus and transitions](menu_and_transitions.md)
- [Saves and integrity](saves_and_integrity.md)

## Tools and experiments

- [Editor](editor.md), [editor improvements](editor_improvements.md),
  [native scene editor](native_scene_editor.md),
  [travel tools](travel_tools.md), [quick resume](quick_resume.md)
- [Experiments](experiments.md), [phase two](phase2_experiments.md),
  [Play/Edit experiments](simple_play_experiments.md),
  [game lab experiments](game_lab_experiments.md)
- [Comparison with the publisher's other games](mediocre_comparison.md),
  [other devkits](other_game_devkits.md),
  [public repository layout](public_repository.md),
  [known limits](unknowns.md)
