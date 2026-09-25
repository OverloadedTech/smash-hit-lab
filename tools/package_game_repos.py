#!/usr/bin/env python3
"""Package the standalone repositories and documentation screenshots, excluding APKs."""

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GAMES = ("smash-hit", "granny-smith", "pinout")
ROOT_FILES = (
    "README.md",
    "LICENSE",
    "THIRD_PARTY.md",
    "CONTRIBUTING.md",
    "REVERSE_ENGINEERING.md",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    ".clang-format",
    "pyproject.toml",
    "project.json",
    "lab.py",
    "requirements.txt",
    "requirements-test.txt",
)
PATTERNS = (
    "native/*.cpp",
    "native/*.hpp",
    "android/java/**/*.java",
    "android/assets/lab/Dobby-MODIFICATIONS.txt",
    "vendor/json.hpp",
    "desktop/*.py",
    "desktop/web/*.js",
    "desktop/web/*.css",
    "desktop/web/*.html",
    "desktop/game_web/*.js",
    "desktop/game_web/*.css",
    "desktop/game_web/*.html",
    "tools/*.py",
    "tools/toolchain.lock.json",
    "docs/*.md",
    "docs/validation.json",
    "docs/version-comparison.json",
    "docs/images/*.webp",
    "tests/*.py",
    "experiments/*.py",
    "experiments/*.js",
    "experiments/verify_diagnostic_log.cpp",
    "experiments/input_driver/*.java",
    ".github/workflows/*.yml",
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def files_for(repo):
    files = {repo / name for name in ROOT_FILES}
    for pattern in PATTERNS:
        files.update(repo.glob(pattern))
    if not all(path.is_file() and not path.is_symlink() for path in files):
        raise ValueError("Missing or linked source input in " + str(repo))
    return sorted(files)


def audit_text(repo, files):
    included = set(files)
    directories = {
        parent
        for path in files
        for parent in path.parents
        if parent.is_relative_to(repo)
    }
    for path in files:
        data = path.read_bytes()
        if path.parent == repo / "docs/images" and path.suffix == ".webp":
            from PIL import Image

            if len(data) > 300_000:
                raise ValueError("Oversized documentation screenshot: " + str(path))
            with Image.open(path) as screenshot:
                if screenshot.format != "WEBP" or max(screenshot.size) > 1600:
                    raise ValueError("Invalid documentation screenshot: " + str(path))
                screenshot.verify()
            continue
        text = data.decode("utf-8")
        if "\x00" in text:
            raise ValueError("Binary data in source allowlist: " + str(path))
        if "/home/" in text or "C:\\\\Users\\\\" in text or "-----BEGIN PRIVATE KEY-----" in text:
            raise ValueError("Workspace path or private key in " + str(path))
        if path.suffix == ".md":
            links = re.findall(r"!?\[([^\]]+)\]\(([^)]+)\)", text)
            links.extend(("image", src) for src in re.findall(r'<img\b[^>]*\bsrc="([^"]+)"', text))
            for label, link in links:
                if ":" in link or link.startswith("#"):
                    continue
                target = (path.parent / link.split("#", 1)[0]).resolve()
                if target not in included and target not in directories:
                    raise ValueError(
                        f"Broken link in {path.relative_to(repo)}: {label} → {link}"
                    )


def audit_git(repo, files):
    # Use a temporary index/worktree to exercise the shipped ignore rules.
    with tempfile.TemporaryDirectory(prefix="repo-git-check-") as temporary:
        work = Path(temporary)
        for path in files:
            destination = work / path.relative_to(repo)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes())
        for name in [
            "input/game.apk",
            "build/lab.keystore",
            "analysis/scene.json",
            "artifacts/game.apk",
            "desktop/web/vendor/three/build/three.module.js",
        ]:
            destination = work / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"private output, must stay ignored")
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=work, check=True)
        subprocess.run(["git", "add", "--all"], cwd=work, check=True)
        tracked = (
            subprocess.check_output(["git", "ls-files", "-z"], cwd=work)
            .decode()
            .split("\x00")
        )
        tracked = set(filter(None, tracked))
        wanted = {path.relative_to(repo).as_posix() for path in files}
        if tracked != wanted:
            raise ValueError("Git file mismatch: " + repr(tracked ^ wanted))
        subprocess.run(
            ["git", "diff", "--cached", "--check"],
            cwd=work,
            check=True,
            capture_output=True,
        )


def package(game, output):
    repo = (ROOT / "repos" / (game + "-lab")).resolve()
    files = files_for(repo)
    audit_text(repo, files)
    audit_git(repo, files)
    validation = json.loads((repo / "docs/validation.json").read_text())
    build = validation["repository_build"]
    if not build.get("passed"):
        raise ValueError("Repository build is not verified: " + game)
    for name, expected in build["source_sha256"].items():
        path = repo / name
        if path not in files or sha256(path.read_bytes()) != expected:
            raise ValueError("Source differs from the successful build: " + name)
    archive = output / (game + "-lab-source.zip")
    temporary = archive.with_suffix(".zip.part")
    manifest = {}
    with zipfile.ZipFile(
        temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=9
    ) as target:
        for path in files:
            relative = path.relative_to(repo).as_posix()
            data = path.read_bytes()
            info = zipfile.ZipInfo(
                repo.name + "/" + relative, date_time=(2026, 9, 9, 0, 0, 0)
            )
            info.create_system = 3
            info.external_attr = (0o100755 if relative == "lab.py" else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, data)
            manifest[relative] = sha256(data)
    with zipfile.ZipFile(temporary) as source:
        if source.testzip() is not None:
            raise ValueError("ZIP integrity failure")
        for name, digest in manifest.items():
            if sha256(source.read(repo.name + "/" + name)) != digest:
                raise ValueError("ZIP content mismatch: " + name)
    temporary.replace(archive)
    return {
        "zip": archive.relative_to(ROOT).as_posix(),
        "bytes": archive.stat().st_size,
        "sha256": sha256(archive.read_bytes()),
        "source_files": len(files),
        "files": manifest,
    }


def main():
    output = ROOT / "artifacts/github"
    output.mkdir(parents=True, exist_ok=True)
    games = {game: package(game, output) for game in GAMES}
    report = {
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "result": "PASS",
        "games": games,
    }
    (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "SHA256SUMS").write_text(
        "".join(info["sha256"] + "  " + Path(info["zip"]).name + "\n" for info in games.values())
    )
    for game, info in games.items():
        print(
            game,
            info["source_files"],
            "files,",
            info["bytes"],
            "bytes,",
            info["sha256"],
        )


if __name__ == "__main__":
    main()
