#!/usr/bin/env python3
"""Inspect Granny Smith level/campaign XML and validate its motion records.

Motion byte widths and the 0x10000 optional-pose bit come from Replay::load in
the supplied 1.3.8 library. Unmapped input bits/fields retain their raw names.
This does not claim a complete replay player or a native editor implementation.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import math
import struct
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RECORD = struct.Struct('<Ih')
POSE = struct.Struct('<6f')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def motion(data, keep_records=False):
    offset, records, pose_count = 0, [], 0
    flags, values = Counter(), Counter()
    while offset < len(data):
        start = offset
        if offset + RECORD.size > len(data):
            raise ValueError('Truncated motion record')
        flag, value = RECORD.unpack_from(data, offset)
        offset += RECORD.size
        pose = None
        if flag & 0x10000:
            if offset + POSE.size > len(data):
                raise ValueError('Truncated motion pose')
            pose = list(POSE.unpack_from(data, offset)); offset += POSE.size
            if not all(math.isfinite(x) for x in pose):
                raise ValueError('Nonfinite motion pose')
            pose_count += 1
        flags[hex(flag)] += 1; values[value] += 1
        if keep_records:
            records.append({'byte_offset': start, 'flags_u32': flag, 'value_i16': value,
                            'pose_floats_in_file_order': pose})
    result = {'bytes_consumed': offset, 'records': sum(flags.values()), 'pose_records': pose_count,
              'flags': dict(flags), 'i16_values': dict(values)}
    if keep_records:
        result['raw_records'] = records
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, default=ROOT / 'incoming/granny-smith/granny-smith.apk')
    parser.add_argument('--out', type=Path, default=ROOT / 'analysis/games/granny-smith/formats.json')
    parser.add_argument('--extract-motion', help='Optional asset path without assets/; raw records are written beside the report')
    args = parser.parse_args(); args.out.parent.mkdir(parents=True, exist_ok=True)
    levels, motions, errors = [], [], []
    campaign, extracted = None, False
    with zipfile.ZipFile(args.apk) as apk:
        root = ET.fromstring(apk.read('assets/game.xml.mp3'))
        campaign = [{'attributes': world.attrib, 'levels': [e.attrib for e in world.findall('level')]}
                    for world in root.findall('world')]
        for name in sorted(apk.namelist()):
            if not name.startswith('assets/') or not name.endswith(('.xml.gz.mp3', '.motion.gz.mp3')):
                continue
            data = apk.read(name)
            try:
                raw = gzip.decompress(data)
                common = {'path': name, 'sha256': sha(data), 'decoded_sha256': sha(raw),
                          'decoded_bytes': len(raw)}
                if name.endswith('.motion.gz.mp3'):
                    extract = args.extract_motion == name[len('assets/'):]
                    parsed = motion(raw, extract)
                    if extract:
                        (args.out.parent / 'extracted-motion.json').write_text(json.dumps({
                            **common, **parsed, 'semantics': 'Raw file order. Input bits, signed short and individual pose components remain partially mapped.'
                        }, indent=2) + '\n')
                        parsed.pop('raw_records'); extracted = True
                    motions.append({**common, **parsed})
                else:
                    level = ET.fromstring(raw)
                    if level.tag != 'level':
                        raise ValueError('Unexpected gzip XML root ' + level.tag)
                    entities = list(level.find('entities'))
                    positions, rotations = [], []
                    for entity in entities:
                        if 'pos' in entity.attrib:
                            p = [float(x) for x in entity.attrib['pos'].split()]
                            if len(p) != 2 or not all(math.isfinite(v) for v in p):
                                raise ValueError('Invalid 2D entity position')
                            positions.append(p)
                        if 'rot' in entity.attrib:
                            rotation = float(entity.attrib['rot'])
                            if not math.isfinite(rotation):
                                raise ValueError('Invalid entity rotation')
                            rotations.append(rotation)
                    for parent in level.iter():
                        for vertex in parent.findall('v'):
                            width = {'shape': 2, 'curve': 6}.get(parent.tag)
                            p = [float(x) for x in (vertex.text or '').split()]
                            if width is None or len(p) != width or not all(math.isfinite(v) for v in p):
                                raise ValueError('Invalid ' + parent.tag + ' vertex record')
                    levels.append({**common, 'attributes': level.attrib,
                                   'entities': dict(Counter(e.tag for e in entities)),
                                   'element_counts': dict(Counter(e.tag for e in level.iter())),
                                   'position_count': len(positions), 'rotation_count': len(rotations),
                                   'entity_position_bounds': None if not positions else {
                                       'min': [min(p[i] for p in positions) for i in range(2)],
                                       'max': [max(p[i] for p in positions) for i in range(2)]}})
            except Exception as error:
                errors.append({'path': name, 'error': str(error)})
    if args.extract_motion and not extracted:
        errors.append({'extract': args.extract_motion, 'error': 'Requested motion was not decoded'})
    report = {'created_utc': datetime.now(timezone.utc).isoformat(), 'apk_sha256': sha(args.apk.read_bytes()),
              'harness_sha256': sha(Path(__file__).read_bytes()),
              'status': 'PASS' if not errors else 'INCOMPLETE', 'errors': errors,
              'counts': {'levels': len(levels), 'motion_files': len(motions),
                         'motion_records': sum(m['records'] for m in motions),
                         'pose_records': sum(m['pose_records'] for m in motions),
                         'campaign_worlds': len(campaign),
                         'campaign_level_entries': sum(len(w['levels']) for w in campaign)},
              'campaign': campaign, 'levels': levels, 'motions': motions,
              'limits': ['Campaign requirements are a dependency graph, not filename ordering.',
                         'Stored authoring coordinates are not complete collision/render geometry.',
                         'Motion records parse exactly; input flag meanings, short-field semantics and playback timing need further tracing.']}
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('status', 'counts', 'errors')}, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
