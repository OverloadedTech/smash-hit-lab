#!/usr/bin/env python3
"""Validate observed asset structures and export an inventory from the actual APK.

No generated geometry is substituted for game assets. Run after APK extraction.
"""
from collections import Counter, defaultdict
from pathlib import Path
import array
import io
import json
import math
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'analysis/apk/assets'
OUT = ROOT / 'analysis/reports'


def texture_info(path):
    data = path.read_bytes()
    kind, payload_size, reserved = struct.unpack_from('<III', data)
    assert len(data) == 12 + payload_size
    assert reserved == 0
    info = dict(kind=kind, payload_size=payload_size)
    if kind == 0:
        jpeg = data[12:]
    elif kind == 1:
        version, width, height, jpeg_size = struct.unpack_from('<4I', data, 12)
        info['payload_header_u32'] = [version, width, height, jpeg_size]
        assert version == 1
        jpeg = data[28:28 + jpeg_size]
        alpha_size, = struct.unpack_from('<I', data, 28 + jpeg_size)
        assert len(data) == 32 + jpeg_size + alpha_size
        decoder = zlib.decompressobj()
        alpha = decoder.decompress(data[32 + jpeg_size:]) + decoder.flush()
        assert decoder.eof and not decoder.unused_data
        assert len(alpha) == width * height
        info['alpha_bytes'] = len(alpha)
    else:
        raise ValueError(f'Unknown MTX kind {kind}')
    with Image.open(io.BytesIO(jpeg)) as decoded:
        assert decoded.format == 'JPEG'
        decoded.load()  # Actually decode the entire payload, not just its header.
        if kind == 1:
            assert decoded.size == (width, height)
        info['width'], info['height'] = decoded.size
        info['decoded_mode'] = decoded.mode
    info['payload_validated'] = True
    return info


def mesh_info(path):
    data = zlib.decompress(path.read_bytes())
    vertices, = struct.unpack_from('<I', data)
    offset = 4 + vertices * 24
    triangles, = struct.unpack_from('<I', data, offset)
    assert len(data) == offset + 4 + triangles * 12, str(path)
    indices = array.array('I', data[offset + 4:])
    if sys.byteorder != 'little':
        indices.byteswap()
    assert len(indices) == triangles * 3
    assert not indices or max(indices) < vertices
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for i in range(vertices):
        vertex = struct.unpack_from('<5f4B', data, 4 + 24 * i)
        assert all(math.isfinite(n) for n in vertex[:5])
        for j in range(3):
            lo[j], hi[j] = min(lo[j], vertex[j]), max(hi[j], vertex[j])
    return dict(vertices=vertices, triangles=triangles, decompressed_bytes=len(data),
                bounds=[lo, hi] if vertices else None)


def font_info(path, unicode):
    tokens = path.read_text().split()
    if not unicode:
        widths = list(map(int, tokens))
        assert widths and all(n >= 0 for n in widths)
        return dict(format='legacy_text_widths', widths=widths, valid=True)
    header = list(map(float, tokens[:2]))
    count = int(tokens[2])
    assert count > 0 and len(tokens) == 3 + 9 * count
    mapping = [list(map(int, tokens[3 + i * 2:5 + i * 2])) for i in range(count)]
    assert all(0 <= cp <= 0x10ffff and 0 <= index < count for cp, index in mapping)
    assert len({cp for cp, _ in mapping}) == count
    start = 3 + count * 2
    glyphs = [list(map(float, tokens[start + i * 7:start + (i + 1) * 7]))
              for i in range(count)]
    assert all(math.isfinite(n) for n in header + [v for glyph in glyphs for v in glyph])
    return dict(format='unicode_text_metrics', header_float_values=header, glyph_count=count,
                codepoints=[cp for cp, _ in mapping], mapping=mapping, glyphs=glyphs, valid=True)


def audio_info(path):
    data = path.read_bytes()
    assert data[:4] == b'OggS' and data[4] == 0 and data[5] & 2
    segment_count = data[26]
    lacing = data[27:27 + segment_count]
    length = 0
    for size in lacing:
        length += size
        if size < 255:
            break
    packet = data[27 + segment_count:27 + segment_count + length]
    assert len(packet) == 30 and packet[:7] == b'\x01vorbis'
    version, channels, rate = struct.unpack_from('<IBI', packet, 7)
    assert version == 0 and channels > 0 and rate > 0 and packet[29] & 1
    return dict(codec='Vorbis', version=version, channels=channels, sample_rate=rate,
                identification_validated=True, full_waveform_decoded=False)


def analyze():
    report = dict(logical_formats=Counter(), xml_roots=Counter(), lua_api_calls=Counter(),
                  segment_elements=Counter(), segment_attributes=defaultdict(Counter),
                  mesh_totals=Counter(), texture_types=Counter(), audio_magic=Counter(), errors=[])
    segments, textures, shaders, levels, fonts, audio = {}, {}, {}, {}, {}, {}
    for path in sorted(ASSETS.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(ASSETS).as_posix()
        logical = rel[:-4] if rel.endswith('.mp3') else rel
        suffix = Path(logical).suffix
        report['logical_formats'][suffix] += 1
        try:
            if suffix == '.mesh':
                info = mesh_info(path)
                segments.setdefault(logical[:-5], {})['mesh'] = info
                report['mesh_totals'].update({k: v for k, v in info.items() if k != 'bounds'})
            elif suffix == '.xml':
                node = ET.fromstring(path.read_bytes())
                report['xml_roots'][node.tag] += 1
                if node.tag == 'segment':
                    elements = [dict(tag=e.tag, attributes=e.attrib) for e in node]
                    segments.setdefault(logical[:-4], {})['xml'] = dict(attributes=node.attrib, elements=elements)
                    for e in node:
                        report['segment_elements'][e.tag] += 1
                        report['segment_attributes'][e.tag].update(e.attrib.keys())
                elif node.tag == 'level':
                    levels[logical] = [dict(tag=e.tag, attributes=e.attrib) for e in node]
            elif suffix == '.lua':
                report['lua_api_calls'].update(re.findall(r'\b(mg[A-Za-z0-9_]+)\s*\(', path.read_text()))
            elif suffix == '.mtx':
                info = texture_info(path)
                report['texture_types'][info['kind']] += 1
                textures[logical] = info
            elif suffix == '.glsl':
                text = path.read_text()
                shaders[logical] = dict(uniforms=re.findall(r'\buniform\s+(\w+)\s+(\w+)', text),
                                       attributes=re.findall(r'\battribute\s+(\w+)\s+(\w+)', text),
                                       vertex='#ifdef VERTEX' in text, fragment='#ifdef FRAGMENT' in text)
            elif suffix == '.ogg':
                magic = path.read_bytes()[:4]
                report['audio_magic'][repr(magic)] += 1
                audio[logical] = audio_info(path)
            elif suffix in ('.fnt', '.ufnt'):
                fonts[rel] = font_info(path, suffix == '.ufnt')
        except Exception as exc:
            report['errors'].append(dict(path=rel, error=f'{type(exc).__name__}: {exc}'))
    for name, value in [('asset_summary', report), ('segments', segments), ('textures', textures),
                        ('shaders', shaders), ('level_rooms', levels), ('fonts', fonts), ('audio', audio)]:
        (OUT / (name + '.json')).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, indent=2, sort_keys=True))
    if report['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    analyze()
