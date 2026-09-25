#!/usr/bin/env python3
"""Fetch the pinned, MIT-licensed Three.js files used by the local desktop editor."""

from pathlib import Path
import hashlib, io, json, tarfile, urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.169.0"
URL = f"https://registry.npmjs.org/three/-/three-{VERSION}.tgz"
SHA256 = "c86d0937570fb425d981e156ddf919c43dbc45d4e91fd7c8dd0de56723b3ec71"
FILES = [
    "build/three.module.js",
    "examples/jsm/controls/OrbitControls.js",
    "examples/jsm/controls/TransformControls.js",
    "LICENSE",
]


def main():
    target = ROOT / "desktop/web/vendor/three"
    target.mkdir(parents=True, exist_ok=True)
    blob = urllib.request.urlopen(URL, timeout=60).read()
    if hashlib.sha256(blob).hexdigest() != SHA256:
        raise ValueError("Three.js archive checksum differs from the pinned dependency")
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        for name in FILES:
            member = archive.getmember("package/" + name)
            if not member.isfile():
                raise ValueError("Unexpected dependency entry")
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.extractfile(member).read())
    report = {
        "package": "three",
        "version": VERSION,
        "url": URL,
        "archive_sha256": hashlib.sha256(blob).hexdigest(),
        "license": "MIT",
        "files": {
            n: hashlib.sha256((target / n).read_bytes()).hexdigest() for n in FILES
        },
    }
    (target / "dependency.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Desktop dependencies installed locally:", target)


if __name__ == "__main__":
    main()
