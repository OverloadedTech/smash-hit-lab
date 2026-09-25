#!/usr/bin/env python3
"""Source-only checks. Requires Git, Bash and g++; --javascript also needs Node."""

import argparse
import ast
from collections import Counter
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_SUFFIXES = {'.apk', '.apks', '.xapk', '.so', '.dex', '.glb', '.mesh',
                    '.mtx', '.ogg', '.mp3', '.keystore', '.jks', '.pem', '.p12'}


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def require_git_checkout():
    probe = subprocess.run(('git', 'rev-parse', '--git-dir'), cwd=ROOT,
                           capture_output=True)
    if probe.returncode != 0:
        raise SystemExit('This check needs a Git checkout: both the file list '
                         'and the ignore-rule assertions come from Git. Clone '
                         'the repository, or run "git init && git add ." here '
                         'first.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--javascript', action='store_true')
    args = parser.parse_args()
    require_git_checkout()
    names = run('git', 'ls-files', '--cached', '--others', '--exclude-standard',
                '-z', capture_output=True).stdout.decode().split('\0')
    counts = Counter()
    for name in sorted(set(filter(None, names))):
        path = ROOT / name
        if not path.exists():  # Unstaged deletions are absent from the checkout.
            continue
        if path.is_symlink() or path.suffix.lower() in PRIVATE_SUFFIXES:
            raise ValueError('Unexpected distributed file: ' + name)
        data = path.read_bytes()
        if (b'-----BEGIN ' + b'PRIVATE KEY-----') in data and path.name != 'package_game_repos.py':
            raise ValueError('Private key marker: ' + name)
        if path.suffix == '.py':
            ast.parse(data, filename=name, feature_version=(3, 11))
            compile(data, name, 'exec')
            counts['Python files'] += 1
        elif path.suffix == '.sh':
            run('bash', '-n', str(path))
            counts['shell files'] += 1
        elif path.suffix == '.js' and args.javascript:
            run('node', '--input-type=module', '--check', input=data)
            counts['JavaScript files'] += 1
        if path.suffix == '.md':
            text = data.decode('utf-8')
            for link in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', text):
                url = urlsplit(link)
                if url.scheme or url.netloc or not url.path:
                    continue
                target = (path.parent / unquote(url.path)).resolve()
                if not target.is_relative_to(ROOT) or not target.exists():
                    raise ValueError(f'Broken local link: {name}: {link}')
                counts['local links'] += 1

    for name in ['incoming/game.apk', 'build/key.keystore', 'private.jks',
                 'analysis/scene.json', 'desktop/projects/export.glb',
                 'tools/sdk/local-tool', 'tools/jdk/local-tool', '.venv/local',
                 'experiments/private/result.json', '__pycache__/file.pyc']:
        run('git', 'check-ignore', '--no-index', '-q', name)

    with tempfile.TemporaryDirectory(prefix='lab-source-check-') as temporary:
        binary = str(Path(temporary) / 'verify-log')
        run('g++', '-std=c++20', '-Wall', '-Wextra',
            'experiments/verify_diagnostic_log.cpp',
            'dev/native/diagnostic_log.cpp', '-o', binary)
        run(binary)
    for label, count in sorted(counts.items()):
        print(f'PASS: {count} {label}')
    print('PASS: ignore fixtures and native diagnostic logger')
    if not args.javascript:
        print('NOT RUN: JavaScript syntax (use --javascript with Node installed)')
    print('NOT RUN: APK builds, Android runtime and browser integration')


if __name__ == '__main__':
    main()
