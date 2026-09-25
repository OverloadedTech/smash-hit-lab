#!/usr/bin/env python3
"""Fetch and build a pinned Apache-2.0 Dobby dependency for the game addons."""
from pathlib import Path
import argparse, hashlib, io, json, subprocess, tarfile, urllib.request
ROOT=Path(__file__).resolve().parents[1]
COMMIT='e9fe7fbecae47a2287e761080f8b1133cc22e8fa'
SHA='b5dddb530ae3b1abe8b61dd3a690eaf0ffe74900b0313c3d1bee0597691cf2d3'
SOURCE=ROOT/'tools/dobby-stable'
TIMEOUT=60
def build(abi):
    if not (SOURCE/'CMakeLists.txt').exists():
        data=urllib.request.urlopen('https://codeload.github.com/jmpews/Dobby/tar.gz/'+COMMIT,timeout=TIMEOUT).read()
        if hashlib.sha256(data).hexdigest()!=SHA:raise RuntimeError('Dobby archive hash mismatch')
        SOURCE.mkdir(parents=True,exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
            for entry in archive.getmembers():
                entry.name='/'.join(entry.name.split('/')[1:])
                if entry.name:archive.extract(entry,SOURCE,filter='data')
        (ROOT/'tools/dobby-stable-source.json').write_text(json.dumps({'repository':'https://github.com/jmpews/Dobby','commit':COMMIT,'archive_sha256':SHA},indent=2)+'\n')
    directory=ROOT/'build/dobby-stable'/abi
    output=directory/'libdobby.a'
    # The pinned upstream header defines a non-inline function in every translation
    # unit. Make its logger and accessor C++ inline entities (no hook logic changes).
    header=SOURCE/'external/logging/logging/logging.h'
    text=header.read_text()
    before='inline static Logger gLogger;\nLogger *Logger::Shared() {'
    after='inline Logger gLogger;\ninline Logger *Logger::Shared() {'
    if before in text:header.write_text(text.replace(before,after))
    elif after not in text:raise RuntimeError('Dobby logging patch anchor differs')
    # Upstream leaves thumb_mode uninitialized for even (ARM) addresses. Heap
    # reuse can therefore install Thumb instructions over an ARM function. This
    # caused a reproducible SIGILL at Granny Smith's b2World::Step on API 23.
    entry=SOURCE/'source/InterceptEntry.cpp'
    text=entry.read_text()
    before='  this->type = type;\n'
    after='  this->type = type;\n  this->thumb_mode = false;\n'
    if after not in text:
        if text.count(before)!=1:raise RuntimeError('Dobby ARM mode patch anchor differs')
        entry.write_text(text.replace(before,after))
    if not output.exists():
        subprocess.run(['cmake','-S',str(SOURCE),'-B',str(directory),'-G','Ninja',
          '-DCMAKE_TOOLCHAIN_FILE='+str(ROOT/'tools/sdk/ndk/android-ndk-r27c/build/cmake/android.toolchain.cmake'),
          '-DANDROID_ABI='+abi,'-DANDROID_PLATFORM=android-21','-DCMAKE_BUILD_TYPE=Release',
          '-DDOBBY_DEBUG=OFF','-DPlugin.SymbolResolver=OFF','-DPlugin.ImportTableReplace=OFF'],check=True)
    subprocess.run(['cmake','--build',str(directory),'--target','dobby_static','-j4'],check=True)
    return output
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('abi',choices=['armeabi-v7a','arm64-v8a','x86_64']);a=p.parse_args();print(build(a.abi))
