#!/usr/bin/env python3
"""Create a source-only local research bundle from an explicit allowlist."""

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / "public-research"
    files = {
        ROOT / name
        for name in [
            "README.md",
            "LICENSE",
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
            "requirements-test.txt",
            "REVERSE_ENGINEERING.md",
            ".gitignore",
            "LICENSING.md",
            "dev/THIRD_PARTY.md",
            "dev/vendor/json.hpp",
            "tools/env.sh",
            "tools/requirements.txt",
            "desktop/requirements.txt",
        ]
    }
    patterns = [
        ".github/**/*.md",
        ".github/workflows/*.yml",
        "docs/*.md",
        "dev/native/*.cpp",
        "dev/native/*.hpp",
        "dev/java/**/*.java",
        "desktop/*.py",
        "desktop/web/*.js",
        "desktop/web/*.html",
        "desktop/web/*.css",
        "desktop/game_web/*.js",
        "desktop/game_web/*.html",
        "desktop/game_web/*.css",
        "tools/*.py",
        "tools/ghidra_scripts/*.java",
        "experiments/*.py",
        "experiments/verify_diagnostic_log.cpp",
        "experiments/probe.js",
        "experiments/pinout_probe.js",
        "experiments/pinout_streaming_controls.js",
        "experiments/granny_probe.js",
        "experiments/input_driver/*.java",
    ]
    for pattern in patterns:
        files.update(ROOT.glob(pattern))
    included = {p.resolve() for p in files}
    included_dirs = {
        parent for p in included for parent in p.parents if parent.is_relative_to(ROOT)
    }
    if target.exists() and not (target / "PUBLIC_EXPORT.json").exists():
        raise SystemExit(
            "Refusing to overwrite an existing non-generated public-research directory"
        )
    previous = {}
    if (target / "PUBLIC_EXPORT.json").exists():
        previous = json.loads((target / "PUBLIC_EXPORT.json").read_text())["files"]
    for name, digest in previous.items():
        p = target / name
        if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise SystemExit(
                "Local edits in exported tree; preserve them before regenerating: "
                + name
            )
    target.mkdir(exist_ok=True)
    manifest = {}
    local_references = []
    for path in sorted(files):
        if not path.is_file():
            raise ValueError("Missing source input " + str(path))
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(
            ("analysis/", "artifacts/", "build/", "dev/assets/", "desktop/web/vendor/")
        ):
            raise ValueError("Private output escaped the allowlist")
        data = path.read_bytes()
        if path.suffix == ".md":
            text = data.decode()
            start = "<!-- LOCAL_ARTIFACTS_BEGIN -->"
            end = "<!-- LOCAL_ARTIFACTS_END -->"
            if start in text:
                text = text.split(start)[0] + text.split(end, 1)[1]

            def local_link(match):
                label, target = match.group(1), match.group(2)
                if ":" in target or target.startswith("#"):
                    return match.group(0)
                resolved = (path.parent / target.split("#", 1)[0]).resolve()
                if resolved in included or resolved in included_dirs:
                    return match.group(0)
                local_references.append(dict(document=relative, target=target))
                return f"{label} (generated locally: `{target}`)"

            text = re.sub(r"!?\[([^\]]+)\]\(([^)]+)\)", local_link, text)
            data = text.encode()
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        manifest[relative] = hashlib.sha256(data).hexdigest()
    for name in set(previous) - set(manifest):
        (target / name).unlink(missing_ok=True)
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Source, original research documentation and licensed tool dependencies. No game APK/assets/decompilation/signing keys.",
        "local_artifact_references": local_references,
        "files": manifest,
    }
    (target / "PUBLIC_EXPORT.json").write_text(json.dumps(report, indent=2) + "\n")
    archive = ROOT / "artifacts/smash-hit-lab-research-source.zip"
    archive.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(manifest):
            z.write(target / name, "smash-hit-lab/" + name)
        z.write(target / "PUBLIC_EXPORT.json", "smash-hit-lab/PUBLIC_EXPORT.json")
    print(
        json.dumps(
            {
                "directory": str(target),
                "zip": str(archive),
                "files": len(manifest),
                "zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
