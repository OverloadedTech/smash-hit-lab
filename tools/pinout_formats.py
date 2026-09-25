#!/usr/bin/env python3
"""Validate PinOut's observed cached mesh and light-map formats.

The packed record layout and quantization constants were traced from the
supplied 1.0.7 native Mesh::loadGeometry/saveGeometry and Table::loadLightMap.
This is a decoder, not a replacement for its curve mesher or table generator.
Reports and optional decoded geometry remain private, locally generated data.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import math
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
RENDER_VERTEX = struct.Struct('<3h3b2fI')
RENDER_FACE = struct.Struct('<B3H')
COLLISION_VERTEX = struct.Struct('<3h3b')
COLLISION_FACE = struct.Struct('<3HB')
LEGACY_RENDER_VERTEX = struct.Struct('<3f3b2fI')
LEGACY_COLLISION_VERTEX = struct.Struct('<6f')
COUNT = struct.Struct('<I')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inflate(data):
    decoder = zlib.decompressobj()
    raw = decoder.decompress(data) + decoder.flush()
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('Incomplete zlib stream or trailing data')
    return raw


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def records(self, layout):
        if self.offset + 4 > len(self.data):
            raise ValueError('Missing record count at byte ' + str(self.offset))
        count, = COUNT.unpack_from(self.data, self.offset)
        self.offset += 4
        end = self.offset + layout.size * count
        if end > len(self.data):
            raise ValueError(f'Count {count} exceeds remaining bytes at {self.offset - 4}')
        records = list(layout.iter_unpack(memoryview(self.data)[self.offset:end]))
        self.offset = end
        return records


def positions(vertices, legacy=False):
    return [[v[i] if legacy else v[i] * 16.0 / 32767.0 for i in range(3)] for v in vertices]


def bounds(points):
    if not points:
        return None
    return {'min': [min(p[i] for p in points) for i in range(3)],
            'max': [max(p[i] for p in points) for i in range(3)]}


def decode_geometry(raw, include_geometry=False, legacy=False):
    reader, meshes = Reader(raw), []
    while reader.offset < len(raw):
        start = reader.offset
        vertices = reader.records(LEGACY_RENDER_VERTEX if legacy else RENDER_VERTEX)
        faces = reader.records(RENDER_FACE)
        collision_vertices = reader.records(LEGACY_COLLISION_VERTEX if legacy else COLLISION_VERTEX)
        collision_faces = reader.records(COLLISION_FACE)
        if any(not math.isfinite(x) for v in vertices for x in v[6:8]):
            raise ValueError('Nonfinite texture coordinates')
        if any(f[0] not in (0, 1) or max(f[1:]) >= len(vertices) for f in faces):
            raise ValueError('Invalid render face indices or boolean')
        if any(max(f[:3]) >= len(collision_vertices) or f[3] > 15 for f in collision_faces):
            raise ValueError('Invalid collision face indices or four-bit flags')
        render_positions, collision_positions = positions(vertices, legacy), positions(collision_vertices, legacy)
        if any(not math.isfinite(x) or abs(x) > 16384
               for points in (render_positions, collision_positions) for p in points for x in p):
            raise ValueError('Invalid mesh-local position')
        if legacy and any(not math.isfinite(x) or abs(x) > 1.01
                          for v in collision_vertices for x in v[3:6]):
            raise ValueError('Invalid legacy collision normal')
        item = {
            'record': len(meshes), 'byte_offset': start, 'byte_length': reader.offset - start,
            'record_sha256': sha(raw[start:reader.offset]),
            'render_vertices': len(vertices), 'render_triangles': len(faces),
            'collision_vertices': len(collision_vertices), 'collision_triangles': len(collision_faces),
            'render_local_bounds': bounds(render_positions),
            'collision_local_bounds': bounds(collision_positions),
            'render_buffer_flags': dict(Counter(f[0] for f in faces)),
            'collision_flags': dict(Counter(f[3] for f in collision_faces))
        }
        if include_geometry:
            item['geometry'] = {
                'render': {'positions': render_positions,
                           'normals': [[x / 127.0 for x in v[3:6]] for v in vertices],
                           'uv': [list(v[6:8]) for v in vertices],
                           'packed_color_u32': [v[8] for v in vertices],
                           'triangles': [list(f[1:]) for f in faces],
                           'buffer_flags': [f[0] for f in faces]},
                'collision': {'positions': collision_positions,
                              'normals': [[x if legacy else x / 127.0 for x in v[3:6]] for v in collision_vertices],
                              'triangles': [list(f[:3]) for f in collision_faces],
                              'flags': [f[3] for f in collision_faces]}
            }
        meshes.append(item)
    return meshes


def decode_observed_layout(raw, include_geometry=False):
    """Accept a layout only after the entire stream and its indices validate.

    The float-position variant is empirically verified in six bundled files;
    the current native loading path was traced for the quantized layout only.
    No filename-based selection or partial-success fallback is used.
    """
    decoded, failures = [], []
    for legacy, name in ((False, 'quantized-positions'), (True, 'float-positions')):
        try:
            meshes = decode_geometry(raw, include_geometry, legacy)
            decoded.append((name, meshes))
        except (ValueError, struct.error) as error:
            failures.append(name + ': ' + str(error))
    if len(decoded) != 1:
        raise ValueError('Ambiguous or unsupported mesh stream: ' + '; '.join(failures))
    return decoded[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, default=ROOT / 'incoming/pinout/pinout.apk')
    parser.add_argument('--out', type=Path, default=ROOT / 'analysis/games/pinout/formats.json')
    parser.add_argument('--extract', help='Optional table path, e.g. production/cp0/level_01; writes local geometry JSON beside the report')
    args = parser.parse_args()
    files, errors = [], []
    extracted = False
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.apk) as apk:
        for name in sorted(apk.namelist()):
            if not name.startswith('assets/levels/') or not name.endswith(('.dat.mp3', '.lgt.mp3')):
                continue
            data = apk.read(name)
            item = {'path': name, 'bytes': len(data), 'sha256': sha(data)}
            try:
                raw = inflate(data)
                item.update(decoded_bytes=len(raw), decoded_sha256=sha(raw))
                if name.endswith('.lgt.mp3'):
                    if len(raw) != 128 * 256:
                        raise ValueError('Expected 128 x 256 GL_ALPHA8 light map')
                    item.update(format='GL_ALPHA8', width=128, height=256,
                                minimum=min(raw), maximum=max(raw))
                else:
                    table = name[len('assets/levels/'):-len('.dat.mp3')]
                    extract = args.extract == table
                    layout, meshes = decode_observed_layout(raw, include_geometry=extract)
                    if extract:
                        (args.out.parent / 'extracted-geometry.json').write_text(json.dumps({
                            'table': table, 'layout': layout, 'source_sha256': sha(data), 'meshes': meshes,
                            'space': 'Mesh local. Authored body transforms, templates and table offsets are not applied.'
                        }, indent=2) + '\n')
                        extracted = True
                        for mesh in meshes:
                            mesh.pop('geometry')
                    item.update(format='packed-mesh-records', layout=layout, table=table, meshes=meshes)
                    xml_name = name[:-len('.dat.mp3')] + '.xml.mp3'
                    if xml_name in apk.namelist():
                        root = ET.fromstring(apk.read(xml_name))
                        bodies = root.findall('./entities/body')
                        item['xml_body_count'] = len(bodies)
                        item['mesh_records_equal_xml_bodies'] = len(meshes) == len(bodies)
                        # Do not assign names to records merely because the counts match.
                        item['xml_mesh_types'] = dict(Counter(c.tag for b in bodies for c in b))
            except Exception as error:
                item['validation_error'] = str(error)
                errors.append({'path': name, 'error': str(error)})
            files.append(item)
    if args.extract and not extracted:
        errors.append({'extract': args.extract, 'error': 'Requested table was not decoded'})
    meshes = [m for f in files for m in f.get('meshes', [])]
    report = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'apk_sha256': sha(args.apk.read_bytes()), 'harness_sha256': sha(Path(__file__).read_bytes()),
        'status': 'PASS' if not errors else 'INCOMPLETE', 'errors': errors,
        'counts': {'files': len(files), 'geometry_files': sum('meshes' in f for f in files),
                   'light_maps': sum(f.get('format') == 'GL_ALPHA8' for f in files),
                   'mesh_records': len(meshes),
                   **{key: sum(m[key] for m in meshes) for key in
                      ('render_vertices', 'render_triangles', 'collision_vertices', 'collision_triangles')}},
        'layouts': dict(Counter(f['layout'] for f in files if 'layout' in f)),
        'files': files,
        'limits': ['Validation covers the observed packed schema, not a complete reimplementation of native meshing.',
                   'Mesh records are not automatically assigned to XML body IDs; persistent meshes may omit records.',
                   'Decoded geometry remains in mesh-local coordinates.',
                   'The float-position layout is validated from six complete payloads; use by the current runtime is not established.']
    }
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
