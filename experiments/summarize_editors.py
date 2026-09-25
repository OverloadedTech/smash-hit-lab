#!/usr/bin/env python3
"""Verify current editor evidence and bind it to the delivered APK and sources."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/os.environ.get('SHLAB_EDITOR_EVIDENCE', 'experiments/editor_improvements')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    build=json.loads((ROOT/'artifacts/build-report.json').read_text())
    device=json.loads((OUT/'device.json').read_text())
    assert digest(ROOT/'artifacts/smash-hit-lab.apk')==build['sha256']==device['apk_sha256']
    assert digest(ROOT/'com.smash.hit.apk')==build['input_sha256']
    checks=[]
    archive=OUT/'harnesses';archive.mkdir(exist_ok=True)
    scripts={'native':'verify_editor_android.py','ui':'verify_editor_ui.py',
             'desktop':'verify_editor_desktop.py','runtime':'verify_editor_runtime.py'}
    for category,script in scripts.items():
        path=OUT/category/'report.json'
        report=json.loads(path.read_text())
        assert report['result']=='PASS',(category,report.get('result'))
        if category!='desktop':
            assert report['apk_sha256']==build['sha256'],category
            assert report['native_pid']==device['native_pid'],category
        else:
            assert report['input_sha256']==build['input_sha256']
            for name,expected in report['source_sha256'].items(): assert digest(ROOT/name)==expected,name
        source=ROOT/'experiments'/script
        expected=report['harness_sha256']
        if digest(source)==expected: (archive/(expected+'.py')).write_bytes(source.read_bytes())
        assert digest(archive/(expected+'.py'))==expected,(category,'Missing executed harness')
        checks.append({'category':category,'result':'PASS','checks':report['checks'],
                       'report':str(path.relative_to(ROOT)),'report_sha256':digest(path),'harness_sha256':expected})
    with zipfile.ZipFile(ROOT/'artifacts/smash-hit-lab.apk') as apk,zipfile.ZipFile(ROOT/'com.smash.hit.apk') as original:
        retained=[n for n in original.namelist() if n in apk.namelist() and n.startswith(('assets/','lib/'))]
        for name in retained: assert original.read(name)==apk.read(name),name
        assert len(retained)==build['unchanged_original_asset_and_library_entries']==2433
        libraries={abi:hashlib.sha256(apk.read('lib/'+abi+'/libshdev.so')).hexdigest() for abi in ['x86_64','arm64-v8a']}
        for abi,expected in libraries.items():
            assert digest(ROOT/'build/debug-apk/native'/abi/'libshdev.so')==expected,abi
        dex=hashlib.sha256(apk.read('classes4.dex')).hexdigest()
        assert digest(ROOT/'build/debug-apk/dex/classes.dex')==dex
    source_hashes={str(p.relative_to(ROOT)):digest(p) for pattern in [
        'dev/native/*.cpp','dev/native/*.hpp','dev/java/**/*.java','desktop/*.py','desktop/web/*.js',
        'desktop/web/*.html','desktop/web/*.css','tools/build_debug.py','experiments/input_driver/*.java'
    ] for p in ROOT.glob(pattern)}
    result={'result':'PASS','created_utc':datetime.now(timezone.utc).isoformat(),'apk_sha256':build['sha256'],
        'input_sha256':build['input_sha256'],'native_pid':device['native_pid'],'abi_runtime_tested':'x86_64',
        'abis_compiled':build['abis'],'unchanged_original_entries':len(retained),
        'addon_library_sha256':libraries,'addon_dex_sha256':dex,'source_sha256':source_hashes,'checks':checks,
        'limits':['No physical ARM test; ARM64 compilation and original layout guards only.',
                  'Runtime edits and undo apply to retained native instances, not a full simulation rollback.',
                  'Groups translate; rotate and scale one object at a time.',
                  'Desktop scripts/physics are not simulated; native body editing remains in Android.',
                  'Startup ANRs occurred on the software emulator; Wait recovery is recorded separately.'],
        'preliminary_evidence':['experiments/editor_improvements/candidate-422b5dc1/',
            'experiments/editor_improvements/candidate-c4419f2e/',
            'experiments/editor_improvements/ui-window-transition-failure/',
            'experiments/editor_improvements/ui-retry-close-label-failure/',
            'experiments/editor_improvements/ui-retry-scroll-position-failure/']}
    path=ROOT/os.environ.get('SHLAB_EDITOR_REPORT', 'artifacts/editor-validation-report.json');path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'result':'PASS','apk_sha256':build['sha256'],'native_pid':device['native_pid'],
                      'categories':len(checks),'behavior_checks':sum(len(c['checks']) for c in checks),
                      'report':str(path.relative_to(ROOT))},indent=2))


if __name__=='__main__':main()
