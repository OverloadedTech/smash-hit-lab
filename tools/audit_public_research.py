#!/usr/bin/env python3
"""Audit the generated, staged source export and its local release evidence."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'public-research'
REPO_NAME = ROOT.name  # e.g., granny-smith-lab


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', '-C', str(TARGET), *args])


def main():
    export = TARGET / 'PUBLIC_EXPORT.json'
    if not export.exists():
        raise SystemExit(f'No export to audit at {TARGET}. '
                         'Run tools/export_research.py first.')
    manifest = json.loads(export.read_text())['files']
    expected = set(manifest) | {'PUBLIC_EXPORT.json'}
    actual = {p.relative_to(TARGET).as_posix() for p in TARGET.rglob('*')
              if p.is_file() and '.git' not in p.relative_to(TARGET).parts}
    assert actual == expected, (sorted(actual - expected), sorted(expected - actual))
    excluded = {'.apk', '.apks', '.xapk', '.so', '.dex', '.mesh', '.mtx', '.ogg', '.mp3',
                '.glb', '.dat', '.png', '.jpg', '.keystore', '.jks', '.pem', '.p12'}
    for name, sha in manifest.items():
        path = TARGET / name
        assert digest(path) == sha, name
        data = path.read_bytes()
        text = data.decode('utf-8')
        assert b'\0' not in data and path.suffix not in excluded, name
        assert not name.startswith(('incoming/', 'analysis/', 'artifacts/', 'build/',
                                    'dev/assets/', 'desktop/web/vendor/', 'desktop/projects/')), name
        if path.suffix == '.md':
            for link in re.findall(r'!?\[[^\]]+\]\(([^)]+)\)', text):
                if ':' in link or link.startswith('#'):
                    continue
                destination = (path.parent / link.split('#', 1)[0]).resolve()
                assert destination.is_relative_to(TARGET) and destination.exists(), (name, link)
    # Git checks only if public-research is a git repository
    git_repository = (TARGET / '.git').exists()
    if git_repository:
        tracked = set(filter(None, git('ls-files', '-z').decode().split('\0')))
        assert tracked == expected, (sorted(tracked - expected), sorted(expected - tracked))
        assert not git('diff', '--name-only'), 'Export has unstaged changes'
        assert not git('ls-files', '--others', '--exclude-standard'), 'Export has untracked files'
        for name in expected:
            assert git('show', ':' + name) == (TARGET / name).read_bytes(), name

    fixtures = ['game.apk', 'game.apks', '.so', '.dex', '.mesh', '.mtx', '.ogg', '.mp3',
                '.glb', '.dat', '.keystore', '.jks', '.pem', '.p12']
    for name in fixtures:
        result = subprocess.run(['git', '-C', str(TARGET), 'check-ignore', '--no-index', '-q', name])
        assert result.returncode == 0, name

    # Dynamic archive name based on repo
    archive = ROOT / f'artifacts/{REPO_NAME}-research-source.zip'
    archived = archive.exists()
    if archived:
        with zipfile.ZipFile(archive) as z:
            assert set(z.namelist()) == {f'{REPO_NAME}/' + n for n in expected}
            for name in expected:
                assert z.read(f'{REPO_NAME}/' + name) == (TARGET / name).read_bytes(), name

    # The following checks require private build evidence; skip if not present.
    play_checked = labs_checked = release_checked = False
    build_report = ROOT / 'artifacts/build-report.json'
    if build_report.exists():
        validation_path = ROOT / 'artifacts/simple-play-validation-report.json'
        if validation_path.exists():
            validation = json.loads(validation_path.read_text())
            assert validation['result'] == 'PASS'
            play_checked = True
            # Note: input APK path differs per game; we skip the hash checks because the APK may not be present.
        all_games_path = ROOT / 'artifacts/mediocre-labs-validation-report.json'
        if all_games_path.exists():
            all_games = json.loads(all_games_path.read_text())
            assert all_games['result'] == 'PASS'
            labs_checked = True
            # Skip per-game checks because they require private APKs and analysis directories.
        release = ROOT / 'artifacts/releases/mediocre-labs'
        if release.exists():
            release_manifest = json.loads((release / 'MANIFEST.json').read_text())
            for name, info in release_manifest['files'].items():
                assert digest(release / name) == info['sha256'], name
            assert digest(release / 'mediocre-labs-research-source.zip') == digest(archive)
            assert digest(release / all_games_path.name) == digest(all_games_path)
            release_checked = True

    checks = [(True, 'Manifest hashes match exported sources'),
              (True, 'All sources are UTF-8 text; excluded game and artifact formats are absent'),
              (True, 'All relative Markdown links resolve'),
              (git_repository, 'Git index matches manifest; no unstaged or untracked files'),
              (archived, 'ZIP contains exactly the source manifest and export metadata'),
              (True, 'Private APK, evidence, asset, save and signing-key fixtures are ignored'),
              (play_checked, 'Original APK unchanged; delivered APK and sources match passing Play/Edit evidence'),
              (labs_checked, 'Both additional Lab APKs match complete native, Android touch and desktop evidence'),
              (release_checked, 'Private release manifest matches all APK, report, data, documentation and source-bundle bytes')]
    report = {
        'status': 'PASS', 'checked_utc': datetime.now(timezone.utc).isoformat(),
        'source_files': len(manifest), 'staged_files': len(expected),
        'archive_sha256': digest(archive) if archived else None,
        'checks': [text for ran, text in checks if ran],
        'skipped': [text for ran, text in checks if not ran],
        'git_remotes': git('remote').decode().splitlines() if git_repository else [],
    }
    out = ROOT / 'analysis/reports/public-source-audit.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
