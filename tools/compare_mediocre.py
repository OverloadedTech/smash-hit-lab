#!/usr/bin/env python3
"""Compare supplied Mediocre APKs without executing or modifying game code.

Reports and binary-derived inventories belong under the ignored analysis/ tree.
Matching symbols establish shared interfaces; they do not establish ABI identity.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import argparse
import gzip
import hashlib
import io
import itertools
import json
import re
import struct
import subprocess
import xml.etree.ElementTree as ET
import zipfile
import zlib

from elftools.elf.elffile import ELFFile
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unzlib(data):
    decoder = zlib.decompressobj()
    raw = decoder.decompress(data) + decoder.flush()
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('Incomplete zlib stream or trailing bytes')
    return raw


def mtx(data):
    """Validate both observed MTX layouts, including their decoded alpha plane."""
    kind, size, reserved = struct.unpack_from('<3I', data)
    wrapped = kind in (0, 1) and size == len(data) - 12 and reserved == 0
    if wrapped:
        data = data[12:]
    if (wrapped and kind == 0) or data.startswith(b'\xff\xd8'):
        jpeg, dimensions, alpha = data, None, None
    else:
        version, width, height, length = struct.unpack_from('<4I', data)
        if version != 1 or not (0 < width <= 16384 and 0 < height <= 16384):
            raise ValueError('Unknown MTX payload header')
        jpeg = data[16:16 + length]
        alpha_size, = struct.unpack_from('<I', data, 16 + length)
        if len(data) != 20 + length + alpha_size:
            raise ValueError('MTX payload size mismatch')
        alpha = unzlib(data[20 + length:])
        if len(alpha) != width * height:
            raise ValueError('MTX alpha plane size mismatch')
        dimensions = (width, height)
    with Image.open(io.BytesIO(jpeg)) as image:
        image.load()
        if image.format != 'JPEG' or (dimensions and image.size != dimensions):
            raise ValueError('MTX JPEG dimensions/format mismatch')
        return {'layout': 'outer-wrapper' if wrapped else 'legacy-payload',
                'dimensions': list(image.size), 'alpha_bytes': len(alpha) if alpha is not None else 0}


def elf_info(data):
    elf = ELFFile(io.BytesIO(data))
    symbols = list(elf.get_section_by_name('.dynsym').iter_symbols())
    exported = [s for s in symbols if s.name and s['st_shndx'] != 'SHN_UNDEF']
    decoded = subprocess.run(['c++filt'], input='\n'.join(s.name for s in exported) + '\n',
                             text=True, capture_output=True, check=True).stdout.splitlines()
    records = []
    for symbol, name in zip(exported, decoded):
        record = {'symbol': symbol.name, 'name': name, 'type': symbol['st_info']['type'],
                  'address': hex(symbol['st_value']), 'size': symbol['st_size']}
        if symbol['st_info']['type'] == 'STT_FUNC' and symbol['st_size'] >= 24:
            for segment in elf.iter_segments():
                delta = symbol['st_value'] - segment['p_vaddr']
                if segment['p_type'] == 'PT_LOAD' and 0 <= delta and delta + symbol['st_size'] <= segment['p_filesz']:
                    start = segment['p_offset'] + delta
                    record['encoded_bytes_sha256'] = sha(data[start:start + symbol['st_size']])
                    break
        records.append(record)
    notes = [n for section in elf.iter_sections() if hasattr(section, 'iter_notes') for n in section.iter_notes()]
    dynamic = elf.get_section_by_name('.dynamic')
    strings = [s.decode('ascii') for s in re.findall(rb'[ -~]{8,}', data)]
    versions = sorted({s for s in strings if re.search(r'Lua [0-9]|Lua.org|Vorbis I|libpng version|zlib version', s)})
    return {'sha256': sha(data), 'machine': elf['e_machine'], 'bits': elf.elfclass,
            'build_ids': [n['n_desc'] for n in notes if n['n_type'] == 'NT_GNU_BUILD_ID'],
            'needed': [t.needed for t in dynamic.iter_tags() if t.entry.d_tag == 'DT_NEEDED'],
            'imports': sorted(s.name for s in symbols if s.name and s['st_shndx'] == 'SHN_UNDEF'),
            'exports': records, 'version_strings': versions}


def inspect(game, apk, library, out, aapt):
    report = {'game': game, 'input': str(apk), 'sha256': sha(apk.read_bytes()), 'bytes': apk.stat().st_size}
    assets, errors, libraries = [], [], {}
    with zipfile.ZipFile(apk) as z:
        report['entries'] = len([i for i in z.infolist() if not i.is_dir()])
        report['dex'] = [n for n in z.namelist() if re.fullmatch(r'classes\d*\.dex', n)]
        for name in z.namelist():
            if name.startswith('lib/') and name.endswith('.so'):
                data = z.read(name)
                libraries[name] = {'bytes': len(data), 'sha256': sha(data)}
        engine_name = 'lib/arm64-v8a/' + library
        report['engine_abi'] = 'arm64-v8a'
        report['engine'] = elf_info(z.read(engine_name))
        for name in sorted(z.namelist()):
            if not name.startswith('assets/') or name.endswith('/'):
                continue
            data = z.read(name)
            logical = name[:-4] if name.endswith('.mp3') else name
            item = {'path': name, 'logical_path': logical, 'bytes': len(data), 'sha256': sha(data)}
            try:
                raw = data
                if logical.endswith('.gz'):
                    raw = gzip.decompress(data)
                    logical = logical[:-3]
                    item.update(compression='gzip', decoded_bytes=len(raw), decoded_sha256=sha(raw))
                if logical.endswith('.xml'):
                    root = ET.fromstring(raw)
                    item.update(format='XML', root=root.tag,
                                element_counts=dict(Counter(e.tag for e in root.iter())))
                    if root.tag in ('level', 'table'):
                        item['root_attributes'] = root.attrib
                        entities = root.find('entities')
                        item['entity_samples'] = [] if entities is None else [
                            {'tag': e.tag, 'attributes': e.attrib} for e in list(entities)[:3]]
                elif logical.endswith('.mtx'):
                    item.update(format='MTX', **mtx(raw))
                elif logical.endswith(('.dat', '.lgt')):
                    raw = unzlib(raw)
                    item.update(format='binary-payload', compression='zlib', decoded_bytes=len(raw),
                                decoded_sha256=sha(raw), first_32_bytes=raw[:32].hex())
                elif raw.startswith(b'OggS'):
                    item['format'] = 'Ogg'
                elif logical.endswith('.lua'):
                    raw.decode('utf-8-sig'); item['format'] = 'Lua-text'
                elif logical.endswith('.glsl'):
                    raw.decode('utf-8-sig'); item['format'] = 'GLSL-text'
                elif logical.endswith('.motion'):
                    item['format'] = 'motion-binary-unparsed'
            except Exception as error:
                item['validation_error'] = str(error)
                errors.append({'path': name, 'error': str(error)})
            assets.append(item)
    report.update(libraries=libraries, assets=assets, validation_errors=errors,
                  asset_formats=dict(Counter(a.get('format', 'other') for a in assets)),
                  xml_roots=dict(Counter(a['root'] for a in assets if 'root' in a)),
                  texture_layouts=dict(Counter(a['layout'] for a in assets if 'layout' in a)))
    if aapt.is_file():
        result = subprocess.run([str(aapt), 'dump', 'badging', str(apk)], text=True, capture_output=True, check=True)
        report['manifest_badging'] = result.stdout.splitlines()
    (out / (game + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    return report


def family(report, prefix):
    return {s['name'] for s in report['engine']['exports'] if s['name'].startswith(prefix)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smash-hit', type=Path, default=ROOT / 'com.smash.hit.apk')
    parser.add_argument('--granny-smith', type=Path, default=ROOT / 'incoming/granny-smith/granny-smith.apk')
    parser.add_argument('--pinout', type=Path, default=ROOT / 'incoming/pinout/pinout.apk')
    parser.add_argument('--out', type=Path, default=ROOT / 'analysis/games/comparison')
    parser.add_argument('--aapt2', type=Path, default=ROOT / 'tools/sdk/build-tools/android-15/aapt2')
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    reports = [inspect(game, path, library, args.out, args.aapt2) for game, path, library in [
        ('smash-hit', args.smash_hit, 'libsmashhit.so'),
        ('granny-smith', args.granny_smith, 'libgrannysmith.so'),
        ('pinout', args.pinout, 'libpinout.so')]]
    pairs = []
    for a, b in itertools.combinations(reports, 2):
        aa = {s['symbol']: s for s in a['engine']['exports']}
        bb = {s['symbol']: s for s in b['engine']['exports']}
        byte_matches = [aa[n]['name'] for n in aa.keys() & bb.keys()
                        if aa[n].get('encoded_bytes_sha256') and
                        aa[n]['encoded_bytes_sha256'] == bb[n].get('encoded_bytes_sha256')]
        a_assets = {s['sha256']: [] for s in a['assets']}
        for s in a['assets']: a_assets[s['sha256']].append(s['path'])
        matches = [{'a': a_assets[s['sha256']], 'b': s['path'], 'sha256': s['sha256']}
                   for s in b['assets'] if s['sha256'] in a_assets]
        pairs.append({'a': a['game'], 'b': b['game'],
                      'shared_qi_interfaces': sorted(family(a, 'Qi') & family(b, 'Qi')),
                      'shared_td_interfaces': sorted(family(a, ('td', 'Td')) & family(b, ('td', 'Td'))),
                      'same_named_function_bytes_minimum_24': sorted(set(byte_matches)),
                      'identical_assets': matches,
                      'identical_libraries': [p for p in a['libraries'].keys() & b['libraries'].keys()
                                              if a['libraries'][p]['sha256'] == b['libraries'][p]['sha256']]})
    summary = {'created_utc': datetime.now(timezone.utc).isoformat(),
               'method': 'ARM64 exported interfaces; encoded function bytes of at least 24 bytes; exact asset/library hashes; parsed XML and both observed MTX layouts.',
               'harness_sha256': sha(Path(__file__).read_bytes()),
               'inputs': {r['game']: r['sha256'] for r in reports},
               'all_three_qi_interfaces': sorted(set.intersection(*(family(r, 'Qi') for r in reports))),
               'all_three_td_interfaces': sorted(set.intersection(*(family(r, ('td', 'Td')) for r in reports))),
               'pairs': pairs, 'asset_validation_errors': {r['game']: r['validation_errors'] for r in reports},
               'limits': ['Shared names are not proof of identical layouts or runtime use.',
                          'Identical function bytes may include helpers and do not establish full engine equivalence.',
                          'Unparsed binary formats and third-party version strings require separate investigation.']}
    (args.out / 'comparison.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({'inputs': summary['inputs'], 'all_three_qi': len(summary['all_three_qi_interfaces']),
                     'all_three_td': len(summary['all_three_td_interfaces']),
                     'pairs': [{k: (len(v) if isinstance(v, list) else v) for k, v in p.items()} for p in pairs],
                     'asset_errors': {r['game']: len(r['validation_errors']) for r in reports}}, indent=2))


if __name__ == '__main__':
    main()
