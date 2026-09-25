#!/usr/bin/env python3
"""Controlled character travel, time-scale and real death-sensor experiments.

Uses a dedicated Granny Smith Lab test installation. The hazard coordinates
come from the original farm/1.xml die sensor; no synthetic death flag is set.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.verify_game_lab import Experiment, close, length, sub


class PlayerExperiment(Experiment):
    def steps(self, count):
        start = self.c.snapshot()['physics_steps']
        return self.wait(lambda s: s['physics_steps'] >= start + count,
                         'native physics steps', timeout=90)

    def level(self, path):
        self.q('mode', value='tools')
        self.q('goto_level', path=path)
        self.frames(3)

    def run(self):
        initial = self.wait(lambda s: s.get('camera_ready'), 'ready')
        self.check('native source matches current APK', initial['addon_source_sha256'] ==
                   self.report['build']['addon_source_sha256'])
        self.q('clear_saved_edits')
        self.q('settings', simulation_speed=1, immortal=False, noclip=True)
        self.level('levels/farm/3.xml')
        s = self.c.snapshot()
        self.check('developer level launch leaves attract replay',
                   not s['native_replay'] and not s['player']['recorded_input'])
        self.q('settings', immortal=True)
        self.q('mode', value='player')
        entities = self.c.snapshot()['native_entities']
        for label, target in [('far forward', [300, 100, 0]),
                              ('far backward', [-100, 100, 0]),
                              ('below level', [-100, -200, 0])]:
            self.q('teleport_player', position=target)
            self.q('pause', value=False)
            s = self.steps(16)
            self.q('pause', value=True)
            self.check(label + ' holds the actual character with noclip',
                       close(s['player']['position'], target, .02) and
                       not s['player']['collision_active'])
            self.check(label + ' preserves the whole level entity set',
                       s['native_entities'] == entities, s['native_entities'])

        self.q('teleport_player', position=[-100, 100, 0])
        deltas = {}
        for speed in [.25, 1, 2]:
            self.q('settings', simulation_speed=speed)
            self.q('pause', value=False)
            s = self.steps(12)
            self.q('pause', value=True)
            deltas[speed] = s['physics_dt']
        self.check('world speed changes the real Box2D integration timestep',
                   abs(deltas[.25] / deltas[1] - .25) < .001 and
                   abs(deltas[2] / deltas[1] - 2) < .001, deltas)
        self.q('settings', simulation_speed=1)
        self.q('mode', value='play')
        s = self.steps(16)
        self.q('pause', value=True)
        self.check('returning to Play restores collision without snapping to spawn',
                   s['player']['collision_active'] and
                   length(sub(s['player']['position'], [-100, 100, 0])) < 10,
                   s['player'])

        hazard = [182.67841, -96.35409, 0]
        self.report['hazard'] = dict(asset='assets/levels/farm/1.xml.gz.mp3',
                                     action='die', position=hazard,
                                     size=[19.40267, 16.3938])
        self.level('levels/farm/1.xml')
        self.q('settings', immortal=True)
        before = self.q('teleport_player', position=hazard)
        self.q('pause', value=False)
        s = self.steps(35)
        self.q('pause', value=True)
        self.check('ordinary teleport stays near its target with collision enabled',
                   s['player']['collision_active'] and
                   length(sub(s['player']['position'], hazard)) < 15, s['player'])
        self.check('immortality prevents a real authored death sensor',
                   s['prevented_deaths'] > before['prevented_deaths'] and
                   not s['player']['dead'] and not s['player']['ragdoll'] and
                   s['death_countdown'] == 0 and s['native_level_state'] == 'play')

        self.q('settings', immortal=False)
        self.level('levels/farm/1.xml')
        self.q('teleport_player', position=hazard)
        self.q('pause', value=False)
        s = self.wait(lambda s: s['player']['dead'] or s['player']['ragdoll'] or
                      s['native_level_state'] != 'play', 'unprotected real hazard', timeout=60)
        self.q('pause', value=True)
        self.check('turning immortality off restores native death at the same sensor',
                   s['player']['dead'] or s['player']['ragdoll'], s['player'])
        self.level('levels/farm/3.xml')
        self.q('settings', immortal=False, simulation_speed=1, noclip=True)
        self.q('mode', value='play')
        s = self.steps(60)
        self.check('normal campaign simulation uses live input after reload',
                   not s['native_replay'] and not s['player']['recorded_input'] and
                   s['player']['collision_active'])
        self.report['final_snapshot'] = s
        self.report['completed'] = True
        self.save()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial', required=True)
    p.add_argument('--port', type=int, default=18768)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--allow-reset', action='store_true')
    a = p.parse_args()
    a.game = 'granny-smith'
    if not a.allow_reset:
        raise SystemExit('Use a dedicated test installation and --allow-reset')
    e = PlayerExperiment(a)
    try:
        e.run()
    except Exception as error:
        e.report['error'] = repr(error)
        e.save()
        raise
    finally:
        e.samples.close()


if __name__ == '__main__':
    main()
