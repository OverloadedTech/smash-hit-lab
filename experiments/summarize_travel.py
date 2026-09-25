#!/usr/bin/env python3
"""Bind navigation and editor behavior evidence to one delivered Lab build."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import argparse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / os.environ.get('SHLAB_TRAVEL_EVIDENCE', 'experiments/travel_tools')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_build():
    build = json.loads((ROOT/'artifacts/build-report.json').read_text())
    apk = ROOT/'artifacts/smash-hit-lab.apk'
    assert digest(apk) == build['sha256']
    with zipfile.ZipFile(apk) as archive:
        for abi in build['abis']:
            assert archive.read('lib/'+abi+'/libshdev.so') == (ROOT/'build/debug-apk/native'/abi/'libshdev.so').read_bytes()
        assert archive.read('classes4.dex') == (ROOT/'build/debug-apk/dex/classes.dex').read_bytes()
        assert archive.read('assets/shdev/navigation.json') == (ROOT/'dev/assets/shdev/navigation.json').read_bytes()
    paths = [p for pattern in ['dev/native/*.cpp', 'dev/native/*.hpp', 'dev/java/**/*.java',
                               'tools/map_navigation.py', 'tools/build_debug.py'] for p in ROOT.glob(pattern)]
    record = {'apk_sha256': build['sha256'], 'created_utc': datetime.now(timezone.utc).isoformat(),
              'description': 'Source state retained for validation; packaged native libraries, DEX and navigation metadata match build products.',
              'files': {str(p.relative_to(ROOT)): digest(p) for p in paths}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'build-sources.json').write_text(json.dumps(record, indent=2)+'\n')
    print('Recorded build sources for', build['sha256'])


def main():
    build = json.loads((ROOT/'artifacts/build-report.json').read_text())
    device = json.loads((OUT/'device.json').read_text())
    assert digest(ROOT/'artifacts/smash-hit-lab.apk') == build['sha256'] == device['apk_sha256']
    assert digest(ROOT/'com.smash.hit.apk') == build['input_sha256']
    sources = json.loads((OUT/'build-sources.json').read_text())
    assert sources['apk_sha256'] == build['sha256']
    for name, expected in sources['files'].items():
        assert digest(ROOT/name) == expected, ('Build source changed during validation', name)
    editor_path = ROOT/'artifacts/editor-validation-report.json'
    editors = json.loads(editor_path.read_text())
    assert editors['result'] == 'PASS'
    assert editors['apk_sha256'] == build['sha256'] and editors['native_pid'] == device['native_pid']
    for name, expected in editors['source_sha256'].items():
        assert digest(ROOT/name) == expected, ('Editor source changed after validation', name)
    archive = OUT/'harnesses'
    archive.mkdir(exist_ok=True)
    groups = []
    for category, script in [('native', 'verify_travel.py'), ('ui', 'verify_travel_ui.py')]:
        path = OUT/category/'report.json'
        report = json.loads(path.read_text())
        assert report['result'] == 'PASS', category
        assert report['apk_sha256'] == build['sha256'] and report['native_pid'] == device['native_pid']
        source = ROOT/'experiments'/script
        expected = report['harness_sha256']
        if digest(source) == expected:
            (archive/(expected+'.py')).write_bytes(source.read_bytes())
        assert digest(archive/(expected+'.py')) == expected, ('Missing executed harness', script)
        assert report['checks'] and all(c['result'] == 'PASS' for c in report['checks'])
        groups.append({'category': 'travel_'+category, 'checks': report['checks'],
                       'report': str(path.relative_to(ROOT)), 'report_sha256': digest(path),
                       'harness_sha256': expected})
    groups.extend(editors['checks'])
    result = {'result': 'PASS', 'created_utc': datetime.now(timezone.utc).isoformat(),
              'apk_sha256': build['sha256'], 'input_sha256': build['input_sha256'],
              'native_pid': device['native_pid'], 'abi_runtime_tested': 'x86_64',
              'abis_compiled': build['abis'], 'unchanged_original_entries': editors['unchanged_original_entries'],
              'addon_library_sha256': editors['addon_library_sha256'],
              'addon_dex_sha256': editors['addon_dex_sha256'],
              'source_sha256': editors['source_sha256'],
              'build_source_record_sha256': digest(OUT/'build-sources.json'),
              'editor_report': str(editor_path.relative_to(ROOT)), 'editor_report_sha256': digest(editor_path),
              'behavior_checks': sum(len(group['checks']) for group in groups), 'groups': groups,
              'limits': ['Physical ARM runtime is untested; both native ABIs compiled.',
                         'Reverse reconstructs original room/object data; it does not rewind physics, audio, breakage or random choices.',
                         'Travel rate is a nominal room-length/32 clock using actual native dt, not a global simulation speed.',
                         'Session unlock leaves recorded checkpoint arrays alone; ordinary gameplay/jumps may still save Lab progress.',
                         'Android startup ANRs occurred on the software emulator and were explicitly recovered with Wait.',
                         'The catalogue GLB is a static artificial sequence, not an executable complete campaign.'],
              'preliminary_evidence': ['experiments/travel_tools/candidate-ee17e24c/',
                                       'experiments/travel_tools/candidate-945d8351/',
                                       'experiments/travel_tools/candidate-fb67d0e5/',
                                       'experiments/travel_tools/ui-menu-scroll-timing-failure/']}
    path = ROOT/'artifacts/travel-validation-report.json'
    path.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ['result','apk_sha256','native_pid','behavior_checks']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--record-build', action='store_true', help='Capture build sources before running the verification procedures')
    args = parser.parse_args()
    record_build() if args.record_build else main()
