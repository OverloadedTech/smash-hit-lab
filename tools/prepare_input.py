#!/usr/bin/env python3
"""Generate private local analysis/mapping inputs from the user's original APK."""

from pathlib import Path
import hashlib
import zipfile
import map_geometry
import map_navigation

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "3b2ffa02fee8ca762f40648f1a9bec5c308764e881dd6a79cacd6dccdb16e338"


def main():
    apk = ROOT / "com.smash.hit.apk"
    if not apk.exists():
        raise SystemExit("Place your own Smash Hit 1.5.14 APK at com.smash.hit.apk")
    if hashlib.sha256(apk.read_bytes()).hexdigest() != EXPECTED:
        raise SystemExit(
            "This APK differs from the exact build investigated by the native addon"
        )
    destination = ROOT / "analysis/apk"
    destination.mkdir(parents=True, exist_ok=True)
    (ROOT / "analysis/reports").mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(apk) as archive:
        for item in archive.infolist():
            if not item.filename.startswith(("assets/", "lib/")) or item.is_dir():
                continue
            path = (destination / item.filename).resolve()
            if not path.is_relative_to(destination.resolve()):
                raise ValueError("Invalid APK entry")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(item))
    map_geometry.build()
    map_navigation.build()
    print(
        "Generated local assets, original libraries and editor face mappings. These outputs are ignored by Git."
    )


if __name__ == "__main__":
    main()
