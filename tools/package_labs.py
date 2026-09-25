#!/usr/bin/env python3
"""Verify exact APK/evidence identities and assemble a private three-game release.

Run after the documented native, Android touch and desktop experiments. This
does not build, install, publish or infer a pass from an unfinished report.
The output contains original game material and is not the public source export.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/releases/mediocre-labs'
GROUPS = {
    'pinout': [('native', 'native-release', 34), ('touch', 'touch-release', 10),
               ('desktop', 'desktop-release', 12)],
    'granny-smith': [('native', 'native-release', 31), ('touch', 'touch-release', 11),
                     ('desktop', 'desktop-release', 12), ('player', 'player-release', 14)],
}
SCOPES = {
    'smash-hit': {'tested_abi': 'x86_64', 'android_api': 30},
    'pinout': {'tested_abi': 'x86_64', 'android_api': 26,
               'environment_note': 'Software CPU emulation; SystemUI package disabled after independent boot/keyguard ANRs. See experiment documentation.'},
    'granny-smith': {'tested_abi': 'armeabi-v7a', 'android_api': 23},
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def relative(path):
    return path.relative_to(ROOT).as_posix()


def check_sources(sources):
    for name, expected in sources.items():
        assert digest(ROOT / name) == expected, 'Source differs from evidence: ' + name


def verify_smash_hit():
    build = read(ROOT / 'artifacts/build-report.json')
    path = ROOT / 'artifacts/simple-play-validation-report.json'
    evidence = read(path)
    assert evidence['result'] == 'PASS' and evidence['behavior_checks'] == 72
    assert digest(ROOT / 'com.smash.hit.apk') == build['input_sha256'] == evidence['input_sha256']
    apk = ROOT / 'artifacts/smash-hit-lab.apk'
    assert digest(apk) == build['sha256'] == evidence['apk_sha256']
    check_sources(evidence['source_sha256'])
    for group in evidence['groups']:
        assert digest(ROOT / group['report']) == group['report_sha256'], group['report']
    return dict(apk=relative(apk), apk_sha256=digest(apk), input_sha256=build['input_sha256'],
                package='com.mediocre.smashhit.dev', abis=['arm64-v8a', 'x86_64'],
                behavior_checks=72, runtime=SCOPES['smash-hit'],
                validation=relative(path), validation_sha256=digest(path))


def verify_game(game):
    build_path = ROOT / 'artifacts' / (game + '-build-report.json')
    build = read(build_path)
    original = ROOT / 'incoming' / game / (game + '.apk')
    apk = ROOT / build['apk']
    assert digest(original) == build['input_sha256'], game
    assert digest(apk) == build['sha256'], game
    check_sources(build['source_sha256'])
    source_id = hashlib.sha256(json.dumps(build['source_sha256'], sort_keys=True,
                                         separators=(',', ':')).encode()).hexdigest()
    assert source_id == build['addon_source_sha256'], game
    retained = 0
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(apk) as target:
        for name in source.namelist():
            if name.startswith('assets/') or (name.startswith('lib/') and name.split('/')[1] in build['abis']):
                assert source.read(name) == target.read(name), 'Original bytes changed: ' + name
                retained += 1
        for abi in build['abis']:
            assert 'lib/' + abi + '/libmlab.so' in target.namelist(), (game, abi)
    assert retained == build['unchanged_original_asset_and_library_entries'], game
    groups = []
    for kind, folder, minimum in GROUPS[game]:
        path = ROOT / 'analysis/games' / game / 'runtime' / folder / 'report.json'
        evidence = read(path)
        assert evidence.get('completed') and evidence.get('passed') and not evidence.get('error'), path
        assert len(evidence['checks']) >= minimum and all(c['passed'] for c in evidence['checks']), path
        assert evidence['build'] == build, 'Report belongs to a different APK: ' + str(path)
        assert evidence['final_snapshot']['addon_source_sha256'] == source_id, path
        check_sources(evidence['experiment_sources'])
        if kind == 'desktop':
            check_sources(evidence['desktop_sources'])
        groups.append(dict(kind=kind, checks=len(evidence['checks']), report=relative(path),
                           report_sha256=digest(path), serial=evidence['serial']))
    return dict(apk=relative(apk), apk_sha256=digest(apk), input_sha256=build['input_sha256'],
                package=build['package'], abis=build['abis'], addon_source_sha256=source_id,
                unchanged_original_entries=retained, runtime=SCOPES[game],
                build_report=relative(build_path), build_report_sha256=digest(build_path),
                behavior_checks=sum(g['checks'] for g in groups), groups=groups)


def main():
    previous = {}
    if OUT.exists():
        if not (OUT / 'MANIFEST.json').exists() and any(OUT.iterdir()):
            raise SystemExit('Existing release folder has no generated manifest; preserve it before packaging')
        if (OUT / 'MANIFEST.json').exists():
            previous = read(OUT / 'MANIFEST.json')['files']
        for name, info in previous.items():
            if (OUT / name).exists() and digest(OUT / name) != info['sha256']:
                raise SystemExit('Local edits in generated release; preserve first: ' + name)
    games = {'smash-hit': verify_smash_hit()}
    games.update({game: verify_game(game) for game in GROUPS})
    report = dict(result='PASS', checked_utc=datetime.now(timezone.utc).isoformat(), games=games,
                  limitations=['ARM64 APK components compile against separately mapped layouts; no physical ARM64 runtime test.',
                               'Tests cover the documented levels and body types, not every campaign object or GPU.',
                               'Desktop editors display/edit geometry; they are not native PC ports of the games.'])
    path = ROOT / 'artifacts/mediocre-labs-validation-report.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {}

    def copy(source, destination):
        target = OUT / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest[destination] = dict(sha256=digest(target), bytes=target.stat().st_size,
                                     source=relative(source))

    copy(path, path.name)
    for game, info in games.items():
        copy(ROOT / info['apk'], game + '-lab.apk')
        if game == 'smash-hit':
            copy(ROOT / info['validation'], 'reports/smash-hit-validation.json')
        else:
            copy(ROOT / info['build_report'], 'reports/' + game + '-build.json')
            for group in info['groups']:
                copy(ROOT / group['report'], 'reports/' + game + '-' + group['kind'] + '.json')
                folder = (ROOT / group['report']).parent
                if group['kind'] == 'native':
                    copy(folder / 'scene.json', 'data/' + game + '/sample-native-scene.json')
                if group['kind'] in ('touch', 'desktop'):
                    name = 'dragged.png' if group['kind'] == 'touch' else 'gizmo-dragged.png'
                    copy(folder / name, 'screenshots/' + game + '-' + group['kind'] + '.png')
        copy(ROOT / 'analysis/games/comparison' / (game + '.json'), 'data/' + game + '/inventory.json')
        source = ROOT / 'analysis/games' / game / 'catalogue.json'
        catalogue = read(source)
        assert catalogue['status'] == 'PASS' and catalogue['input_sha256'] == info['input_sha256'], source
        assert catalogue['harness_sha256'] == digest(ROOT / 'tools/catalogue_games.py'), source
        copy(source, 'data/' + game + '/catalogue.json')
    copy(ROOT / 'analysis/games/comparison/comparison.json', 'data/shared-technology.json')
    for game in GROUPS:
        source = ROOT / 'analysis/games' / game / 'formats.json'
        assert read(source)['status'] == 'PASS', source
        assert read(source)['apk_sha256'] == games[game]['input_sha256'], source
        copy(source, 'data/' + game + '/formats.json')
    for name in ['segments.json', 'level_rooms.json', 'textures.json', 'audio.json', 'shaders.json']:
        copy(ROOT / 'analysis/reports' / name, 'data/smash-hit/' + name)
    copy(ROOT / 'artifacts/smash-hit-lab-research-source.zip', 'mediocre-labs-research-source.zip')
    exported = ROOT / 'public-research'
    source_manifest = read(exported / 'PUBLIC_EXPORT.json')['files']
    for name, expected in source_manifest.items():
        assert digest(exported / name) == expected, name
        copy(exported / name, 'source/' + name)
    copy(exported / 'PUBLIC_EXPORT.json', 'source/PUBLIC_EXPORT.json')
    instructions = '''# Three-game local Lab release

Install the APK for the game you want. These are separate Lab apps and keep
separate saves from the original games. An existing Lab can be updated in place.

- Smash Hit Lab: ARM64/x86_64. Use Play and Edit; drag objects, then Save & resume.
- Granny Smith Lab: ARMv7/ARM64, Android 5+. Use LAB, Camera or Edit in the top bar.
- PinOut Lab: ARM64/x86_64, Android 8+. Use LAB, Camera or Edit in the top bar.

In Granny Smith and PinOut, Camera/Edit pause the world. Close the panel to fly
or drag objects. Save selection keeps edits for later runs. Play restores the
original view and controls. Run/Pause toggles simulation independently.
LAB contains player movement/noclip, death protection or unlimited time, FOV,
speed controls and the full searchable level/table list.

Android touch, native body/collision/persistence and desktop gizmo checks are
recorded under reports/. Runtime tests used x86_64 for Smash Hit and PinOut,
and ARMv7 for Granny Smith. ARM64 has not been tested on a physical device.

data/ contains private generated APK inventories, campaign/asset catalogues,
format reports and Smash Hit segment/room/texture/audio/shader metadata. Each
new Lab has a sample native scene JSON that can be opened in its desktop editor
without a connected phone. Read a fresh scene before applying changes to a live
game; these samples retain the original test process/scene identity. Long event
logs remain in the workspace's analysis/ directories. Reproduce further data
with the source tools and your compatible original APKs.

source/ and the source ZIP include all three games' tools, documentation and
build instructions. Start with source/README.md and source/docs/other_game_devkits.md. The
desktop editors need Python, the pinned Three.js files (tools/setup_desktop.py),
a WebGL browser and ADB for a live Granny Smith/PinOut connection. They are
geometry editors; a native Windows/Linux game port is a separate phase.

This release folder contains original game material. For repository publication,
use the separately audited source bundle and review LICENSING.md in that bundle.
No APK, game assets, decompilation, user saves or signing keys belong in that
source export. Nothing has been uploaded to GitHub.
'''
    readme = OUT / 'README.md'
    readme.write_text(instructions)
    manifest['README.md'] = dict(sha256=digest(readme), bytes=readme.stat().st_size,
                                source='generated by tools/package_labs.py')
    for name in set(previous) - set(manifest):
        (OUT / name).unlink(missing_ok=True)
    (OUT / 'MANIFEST.json').write_text(json.dumps(dict(created_utc=report['checked_utc'],
        private_game_material=True, files=manifest), indent=2) + '\n')
    print(json.dumps(dict(result='PASS', release=str(OUT),
        checks={game: data['behavior_checks'] for game, data in games.items()},
        files=len(manifest)), indent=2))


if __name__ == '__main__':
    main()
