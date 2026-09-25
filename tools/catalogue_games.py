#!/usr/bin/env python3
"""Extract reproducible, private level catalogues from the three supplied APKs.

PinOut order and Granny Smith dependencies come from game.xml. Smash Hit's
room lists and segment catalogue are separate: scripts choose a run's actual
segment instances. This does not pretend that ZIP order is a playable route.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import gzip
import hashlib
import json
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    'smash-hit': ('com.smash.hit.apk', '3b2ffa02fee8ca762f40648f1a9bec5c308764e881dd6a79cacd6dccdb16e338'),
    'granny-smith': ('incoming/granny-smith/granny-smith.apk', 'cb5eb4d70bab1b2c9da9210b18dfecbde09314c2efd0fa3288fcbacd55efda03'),
    'pinout': ('incoming/pinout/pinout.apk', '81c0f9048c2c12731fefcf0373f0fccb28a2e0626288bc826ba66f5002f37ab7'),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def xml(apk, name):
    raw = apk.read(name)
    return ET.fromstring(gzip.decompress(raw) if raw.startswith(b'\x1f\x8b') else raw)


def resolve(apk, path):
    choices = ['assets/' + path + ending for ending in ('.mp3', '.gz.mp3', '')]
    found = [name for name in choices if name in apk.namelist()]
    if len(found) != 1:
        raise ValueError('Expected one native asset for ' + path + ': ' + repr(found))
    return found[0]


def catalogue(game):
    input_path, expected = INPUTS[game]
    path = ROOT / input_path
    if sha(path.read_bytes()) != expected:
        raise ValueError('Unsupported input hash: ' + game)
    result = dict(game=game, input_sha256=expected,
                  created_utc=datetime.now(timezone.utc).isoformat(),
                  harness_sha256=sha(Path(__file__).read_bytes()), status='PASS',
                  evidence='CONFIRMED static XML; runtime state and procedural choices are separate.')
    with zipfile.ZipFile(path) as apk:
        assets = []
        for name in sorted(apk.namelist()):
            if not name.startswith(('assets/levels/', 'assets/segments/')) or not name.endswith(('.xml.mp3', '.xml.gz.mp3')):
                continue
            root = xml(apk, name)
            item = dict(asset=name, sha256=sha(apk.read(name)), root=root.tag,
                        attributes=dict(root.attrib), element_counts=dict(Counter(n.tag for n in root.iter())))
            if game == 'smash-hit' and root.tag == 'level':
                item['ordered_room_definitions'] = [dict(tag=n.tag, attributes=dict(n.attrib)) for n in root]
            assets.append(item)
        result['assets'] = assets
        if game == 'pinout':
            document = xml(apk, 'assets/game.xml.mp3')
            groups, ordered = [], []
            for group_index, level in enumerate(document.findall('level')):
                indices = []
                for table in level.findall('table'):
                    key = table.attrib['type']
                    asset = resolve(apk, 'levels/' + key + '.xml')
                    root = xml(apk, asset)
                    assert root.tag == 'table', asset
                    index = len(ordered)
                    indices.append(index)
                    ordered.append(dict(index=index, group=group_index, type=key,
                                        reference_attributes=dict(table.attrib), asset=asset,
                                        table_attributes=dict(root.attrib)))
                groups.append(dict(index=group_index, attributes=dict(level.attrib), table_indices=indices))
            result.update(game_attributes=dict(document.attrib), campaign_groups=groups, ordered_tables=ordered,
                          distinct_campaign_paths=len({item['asset'] for item in ordered}))
            assert len(ordered) == 125 and result['distinct_campaign_paths'] == 122 and len(groups) == 9
            assert sum(a['root'] == 'table' for a in assets) == 167
        elif game == 'granny-smith':
            document = xml(apk, 'assets/game.xml.mp3')
            worlds, entries = [], []
            for world in document.findall('world'):
                ids = []
                for level in world.findall('level'):
                    asset = resolve(apk, level.attrib['path'])
                    assert xml(apk, asset).tag == 'level', asset
                    ids.append(level.attrib['name'])
                    entries.append(dict(world=world.attrib['name'], attributes=dict(level.attrib), asset=asset,
                                        requires=level.attrib.get('require', '').split()))
                worlds.append(dict(attributes=dict(world.attrib), level_ids=ids))
            known = {entry['attributes']['name'] for entry in entries}
            assert all(set(entry['requires']) <= known for entry in entries)
            assert len(entries) == 57 and len(worlds) == 4 and len(assets) == 58
            result.update(worlds=worlds, campaign_entries=entries,
                          ordering_note='Document order is retained. Unlock requirements are explicit dependencies, not filename order.')
        else:
            assert sum(a['root'] == 'segment' for a in assets) == 643
            result['ordering_note'] = 'No single canonical segment ordering is claimed. Room Lua scripts select/generate segment instances during a run.'
    return result


def main():
    for game in INPUTS:
        result = catalogue(game)
        path = ROOT / 'analysis/games' / game / 'catalogue.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2) + '\n')
        print(game, result['status'], len(result['assets']), 'level/segment/table XML assets', path)


if __name__ == '__main__':
    main()
