#!/usr/bin/env python3
"""Extract the game's own campaign ordering for the private runtime addon."""
from pathlib import Path
import hashlib
import json
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def build():
    apk = ROOT / 'com.smash.hit.apk'
    with zipfile.ZipFile(apk) as archive:
        game = ET.fromstring(archive.read('assets/game.xml.mp3'))
        levels = []
        for index, node in enumerate(game.find('levels').findall('level')):
            name = node.attrib['name']
            if not name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in name):
                raise ValueError('Unexpected campaign asset name')
            source = f'levels/{name}.xml'
            document = ET.fromstring(archive.read('assets/' + source + '.mp3'))
            levels.append({'index': index, 'name': name, 'source': source,
                           'rooms': [dict(room.attrib) for room in document.findall('room')]})
    out = ROOT / 'dev/assets/shdev/navigation.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'version': 1, 'input_sha256': hashlib.sha256(apk.read_bytes()).hexdigest(),
                              'source': 'game.xml', 'levels': levels}, indent=2) + '\n')
    return out


if __name__ == '__main__':
    print(build())
