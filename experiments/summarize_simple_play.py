#!/usr/bin/env python3
"""Bind passing Play/Edit and regression evidence to the delivered APK."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/os.environ.get('SHLAB_PLAY_EVIDENCE','experiments/simple_play')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())


def main():
    build=read(BASE/'build-report.json');apk=ROOT/'artifacts/smash-hit-lab.apk'
    assert sha(apk)==build['sha256'] and sha(ROOT/'com.smash.hit.apk')==build['input_sha256']
    sources=read(BASE/'sources.json')
    current={str(p.relative_to(ROOT)) for pattern in ['dev/native/*.cpp','dev/native/*.hpp','dev/java/**/*.java'] for p in ROOT.glob(pattern)}|{'tools/build_debug.py'}
    assert current==set(sources),'Compiled product file set changed'
    for name,digest in sources.items():
        assert sha(ROOT/name)==digest and sha(BASE/'source'/name)==digest,name
    groups=[];pids=set()
    entries=[('play_native','native/report.json',15),('play_touch','ui/report.json',8),
        ('menu_original','contexts/report.json',4),('cold_persistence','cold/report.json',3),
        ('editor_native','editor-regression/native/report.json',8),
        ('editor_desktop','editor-regression/desktop/report.json',11),
        ('desktop_to_game','editor-regression/runtime/report.json',8),
        ('travel_native','travel-regression/native/report.json',15)]
    for category,name,count in entries:
        path=BASE/name;r=read(path)
        assert r['result']=='PASS' and len(r['checks'])==count,(category,r.get('result'),len(r.get('checks',[])))
        if 'apk_sha256' in r:
            assert r['apk_sha256']==build['sha256'] and r['game_build_id']=='ac3b897010a22367c4829bf6429e90e74f5b0fce'
            pids.add(r['native_pid'])
        else:assert r['input_sha256']==build['input_sha256']
        if 'cold_device' in r:
            assert r['cold_device']['native_pid']!=r['native_pid']
            assert r['cold_device']['apk_sha256']==build['sha256'];pids.add(r['cold_device']['native_pid'])
        for check in r['checks']:
            if isinstance(check,dict):assert check['result']=='PASS',check
        for source,digest in r.get('source_sha256',{}).items():assert sha(ROOT/source)==digest,source
        for source,digest in r.get('helper_sources',{}).items():
            archived=BASE/'harness-sources'/(digest+Path(source).suffix)
            assert archived.exists() and sha(archived)==digest,(category,source)
        if (path.parent/'executed-harness.py').exists():assert sha(path.parent/'executed-harness.py')==r['harness_sha256']
        groups.append({'category':category,'report':str(path.relative_to(ROOT)),
            'report_sha256':sha(path),'harness_sha256':r['harness_sha256'],'checks':r['checks']})
    # Native binary packaging and unchanged original bytes are rechecked here.
    libraries={};retained=0
    with zipfile.ZipFile(ROOT/'com.smash.hit.apk') as original,zipfile.ZipFile(apk) as modified:
        for name in original.namelist():
            if name.startswith(('assets/','lib/')) and name in modified.namelist():
                assert original.read(name)==modified.read(name),name;retained+=1
        for abi in build['abis']:libraries[abi]=hashlib.sha256(modified.read('lib/'+abi+'/libshdev.so')).hexdigest()
        dex=hashlib.sha256(modified.read('classes4.dex')).hexdigest()
    assert retained==build['unchanged_original_asset_and_library_entries']==2433
    binary=ROOT/'build/simple-play/verify-diagnostic-log'
    subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror',str(ROOT/'experiments/verify_diagnostic_log.cpp'),
        str(ROOT/'dev/native/diagnostic_log.cpp'),'-o',str(binary)],check=True)
    log_result=subprocess.check_output([str(binary)],text=True).strip()
    report={'result':'PASS','created_utc':datetime.now(timezone.utc).isoformat(),
        'apk_sha256':build['sha256'],'input_sha256':build['input_sha256'],
        'native_pids':sorted(pids),'abi_runtime_tested':'x86_64','abis_compiled':build['abis'],
        'unchanged_original_entries':retained,'source_sha256':sources,'groups':groups,
        'behavior_checks':sum(len(g['checks']) for g in groups),
        'diagnostic_log_host_check':{'result':log_result,'source_sha256':sha(ROOT/'experiments/verify_diagnostic_log.cpp')},
        'addon_library_sha256':libraries,'addon_dex_sha256':dex,
        'limits':['ARM64 compiled/static-inspected; no physical ARM runtime test',
            'Software emulator startup ANRs/recovery are separately recorded',
            'Saved source transforms are not a full physics/script save',
            'Reverse reconstructs source rooms, not past simulation state',
            'Desktop editor is a geometry tool; native PC game is a deferred phase']}
    out=ROOT/'artifacts/simple-play-validation-report.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['result','apk_sha256','native_pids','behavior_checks']},indent=2))


if __name__=='__main__':main()
