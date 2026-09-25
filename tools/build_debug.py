#!/usr/bin/env python3
"""Build the isolated developer APK from the preserved input and addon sources.

Run tools/bootstrap.py once, source tools/env.sh, then python tools/build_debug.py.
No game source is reconstructed or substituted. Original game libraries and
assets are copied byte-for-byte; the addon uses verified relocation hooks.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
try:
    from . import map_navigation
except ImportError:
    import map_navigation

ROOT=Path(__file__).resolve().parents[1]
SDK=ROOT/'tools/sdk'
BT=SDK/'build-tools/android-15'
JDK=next((ROOT/'tools/jdk').glob('jdk-*'), ROOT/'tools/jdk/not-installed')
NDK=SDK/'ndk/android-ndk-r27c/toolchains/llvm/prebuilt/linux-x86_64'
WORK=ROOT/'build/debug-apk'
INPUT_SHA='3b2ffa02fee8ca762f40648f1a9bec5c308764e881dd6a79cacd6dccdb16e338'
ENV=dict(os.environ,JAVA_HOME=str(JDK),ANDROID_SDK_ROOT=str(SDK))
ENV['PATH']=str(JDK/'bin')+':'+ENV.get('PATH','')

def run(*args):
    print('+',' '.join(map(str,args)),flush=True)
    subprocess.run(list(map(str,args)),cwd=ROOT,env=ENV,check=True)

def prepare():
    original=ROOT/'com.smash.hit.apk'
    if hashlib.sha256(original.read_bytes()).hexdigest()!=INPUT_SHA:
        raise SystemExit('APK SHA-256 differs from the reverse-engineered build')
    map_navigation.build()
    source=ROOT/'analysis/decoded'
    if not source.exists():run(JDK/'bin/java','-jar',ROOT/'tools/apktool.jar','d',original,'-o',source)
    target=WORK/'decoded'
    if not target.exists():shutil.copytree(source,target,ignore=shutil.ignore_patterns('build','dist'))
    android='{http://schemas.android.com/apk/res/android}'
    ET.register_namespace('android',android[1:-1])
    manifest=ET.parse(source/'AndroidManifest.xml');root=manifest.getroot();old=root.attrib['package'];new=old+'.dev';root.set('package',new)
    app=root.find('application');app.set(android+'label','Smash Hit Lab');app.set(android+'debuggable','true');app.set(android+'extractNativeLibs','true')
    for node in root.iter():
        for key,value in list(node.attrib.items()):
            if key==android+'authorities':node.set(key,value.replace(old,new))
            if value==old+'.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION':node.set(key,new+'.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION')
    manifest.write(target/'AndroidManifest.xml',encoding='utf-8',xml_declaration=True)
    activity=Path('smali_classes3/com/mediocre/smashhit/MainActivity.smali')
    text=(source/activity).read_text()
    marker='    invoke-super {p0, p1}, Lcom/google/androidgamesdk/GameActivity;->onCreate(Landroid/os/Bundle;)V'
    assert text.count(marker)==1
    text=text.replace(marker,'    invoke-static {p0}, Ldev/smashhit/DevBridge;->prepare(Landroid/app/Activity;)V\n\n'+marker+'\n\n    invoke-static {p0}, Ldev/smashhit/DevBridge;->install(Landroid/app/Activity;)V')
    assert '.method public dispatchKeyEvent(' not in text
    text+='''
.method public dispatchKeyEvent(Landroid/view/KeyEvent;)Z
    .locals 1
    invoke-static {p1}, Ldev/smashhit/DevBridge;->handleKey(Landroid/view/KeyEvent;)Z
    move-result v0
    if-eqz v0, :original_dispatch
    const/4 v0, 0x1
    return v0
    :original_dispatch
    invoke-super {p0, p1}, Lcom/google/androidgamesdk/GameActivity;->dispatchKeyEvent(Landroid/view/KeyEvent;)Z
    move-result v0
    return v0
.end method
'''
    (target/activity).write_text(text)
    # The investigated layouts and addon support these two 64-bit ABIs only.
    for abi in ['x86','armeabi-v7a']:
        if (target/'lib'/abi).exists():shutil.rmtree(target/'lib'/abi)
    return target

def native(abis):
    output={}
    for abi in abis:
        dest=WORK/'native'/abi;dest.mkdir(parents=True,exist_ok=True)
        triple={'x86_64':'x86_64-linux-android26','arm64-v8a':'aarch64-linux-android26'}[abi]
        source=list((ROOT/'dev/native').glob('*.cpp'))
        run(NDK/'bin'/(triple+'-clang++'),'-std=c++20','-shared','-fPIC','-fvisibility=hidden','-O2','-g','-Wall','-Wextra','-Wno-unused-parameter','-Wno-sign-compare','-static-libstdc++','-Wl,--exclude-libs,ALL','-Wl,-z,max-page-size=16384',*source,'-o',dest/'libshdev.so','-llog','-landroid','-ldl','-lGLESv2')
        shutil.copy2(dest/'libshdev.so',dest/'libshdev.symbols.so')
        run(NDK/'bin/llvm-strip','--strip-debug',dest/'libshdev.so')
        output[abi]=dest/'libshdev.so'
    return output

def java():
    # Removed/renamed anonymous classes must not leak into incremental builds.
    classes=WORK/'classes';shutil.rmtree(classes,ignore_errors=True);classes.mkdir(parents=True)
    dex=WORK/'dex';shutil.rmtree(dex,ignore_errors=True);dex.mkdir()
    run(JDK/'bin/javac','--release','8','-classpath',SDK/'platforms/android-35/android.jar','-d',classes,*sorted((ROOT/'dev/java').rglob('*.java')))
    run(JDK/'bin/jar','cf',WORK/'addon.jar','-C',classes,'.')
    run(BT/'d8','--min-api','26','--lib',SDK/'platforms/android-35/android.jar','--output',dex,WORK/'addon.jar')
    return dex/'classes.dex'

def package(target,libraries,dex):
    base=WORK/'base.apk'
    run(JDK/'bin/java','-jar',ROOT/'tools/apktool.jar','b',target,'-o',base)
    unsigned=WORK/'unsigned.apk'
    with zipfile.ZipFile(base) as src,zipfile.ZipFile(unsigned,'w') as dst:
        for entry in src.infolist():
            if entry.filename.startswith('META-INF/') and entry.filename.endswith(('.SF','.RSA','.DSA','.MF')):continue
            if entry.filename.startswith('lib/') and entry.filename.split('/')[1] not in libraries:continue
            dst.writestr(entry,src.read(entry.filename))
        dst.write(dex,'classes4.dex',compress_type=zipfile.ZIP_DEFLATED)
        for abi,p in libraries.items():dst.write(p,'lib/'+abi+'/libshdev.so',compress_type=zipfile.ZIP_STORED)
        for p in sorted((ROOT/'dev/assets').rglob('*')):
            if p.is_file():dst.write(p,'assets/'+p.relative_to(ROOT/'dev/assets').as_posix(),compress_type=zipfile.ZIP_DEFLATED)
    aligned=WORK/'aligned.apk';run(BT/'zipalign','-f','-P','16','4',unsigned,aligned)
    key=ROOT/'build/shdev.keystore'
    if not key.exists():run(JDK/'bin/keytool','-genkeypair','-keystore',key,'-storepass','android','-keypass','android','-alias','shdev','-keyalg','RSA','-keysize','2048','-validity','3650','-dname','CN=Smash Hit Local Development')
    result=ROOT/'artifacts/smash-hit-lab.apk';result.parent.mkdir(exist_ok=True)
    run(BT/'apksigner','sign','--ks',key,'--ks-key-alias','shdev','--ks-pass','pass:android','--key-pass','pass:android','--out',result,aligned)
    run(BT/'apksigner','verify','--verbose',result)
    # Fail the build if any original shipped game data/library was changed.
    with zipfile.ZipFile(ROOT/'com.smash.hit.apk') as original,zipfile.ZipFile(result) as built:
        names=set(built.namelist());checked=0
        for p in original.namelist():
            if (p.startswith('assets/') or p.startswith('lib/')) and p in names:
                assert original.read(p)==built.read(p),p
                checked+=1
    report={'apk':str(result.relative_to(ROOT)),'sha256':hashlib.sha256(result.read_bytes()).hexdigest(),'input_sha256':INPUT_SHA,'abis':list(libraries),'unchanged_original_asset_and_library_entries':checked,'package':'com.mediocre.smashhit.dev'}
    (ROOT/'artifacts/build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--abi',action='append',choices=['x86_64','arm64-v8a']);args=parser.parse_args()
    if not (JDK/'bin/java').is_file():
        raise SystemExit('Missing local JDK. Run python tools/bootstrap.py --components build, then source tools/env.sh.')
    if not (ROOT/'com.smash.hit.apk').is_file():
        raise SystemExit('Supply the compatible Smash Hit APK at com.smash.hit.apk; see README.md.')
    WORK.mkdir(parents=True,exist_ok=True)
    target=prepare();libs=native(args.abi or ['x86_64','arm64-v8a']);dex=java();package(target,libs,dex)
