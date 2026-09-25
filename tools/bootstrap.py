#!/usr/bin/env python3
"""Install a local, rootless APK analysis/build/emulation toolchain.

Downloads remain in tools/downloads. Android archive checksums come from the
official repository metadata; GitHub release assets and the JDK use SHA-256.
"""

import concurrent.futures
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent
DL = ROOT / "downloads"
DL.mkdir(exist_ok=True)
TIMEOUT = 60


def get_json(url):
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
        return json.load(response)


def metadata():
    """A clean checkout must not depend on previously downloaded metadata."""
    releases = {
        "iBotPeaches/Apktool": "v3.0.3",
        "skylot/jadx": "v1.5.6",
        "NationalSecurityAgency/ghidra": "Ghidra_12.1.3_build",
    }
    for repo, tag in releases.items():
        path = DL / (repo.split("/")[-1] + "-release.json")
        if not path.exists():
            path.write_text(
                json.dumps(
                    get_json(f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
                )
            )
        if json.loads(path.read_text()).get("tag_name") != tag:
            raise ValueError("Unexpected cached release metadata: " + str(path))
    for filename, url in {
        "sdk.xml": "https://dl.google.com/android/repository/repository2-3.xml",
        "images.xml": "https://dl.google.com/android/repository/sys-img/android/sys-img2-3.xml",
    }.items():
        path = DL / filename
        if not path.exists():
            with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
                path.write_bytes(response.read())


def file_digest(path, algorithm):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, algorithm).hexdigest()


def fetch(url, filename, checksum, algorithm="sha256"):
    if not checksum:
        raise ValueError(
            "Refusing to install without a published checksum: " + filename
        )
    dest = DL / filename
    if not dest.exists():
        temp = dest.with_suffix(dest.suffix + ".part")
        with urllib.request.urlopen(url, timeout=TIMEOUT) as source, temp.open(
            "wb"
        ) as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
        digest = file_digest(temp, algorithm)
        if digest != checksum:
            # Keeping the rejected bytes under the final name would cache them
            # for every later run, which never downloads an existing file again.
            temp.unlink()
            raise ValueError(f"Checksum mismatch: {url}: {digest} != {checksum}")
        temp.rename(dest)
    else:
        digest = file_digest(dest, algorithm)
        if digest != checksum:
            raise ValueError(f"Checksum mismatch: {dest}: {digest} != {checksum}")
    print(f"verified {filename}: {algorithm}={digest}", flush=True)
    return dest


def unzip(archive, target):
    target.mkdir(parents=True, exist_ok=True)
    base = target.resolve()
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            if not (base / entry.filename).resolve().is_relative_to(base):
                raise ValueError(entry.filename)
            mode = entry.external_attr >> 16
            if mode & 0o170000 == 0o120000:
                dest = base / entry.filename
                link = z.read(entry).decode()
                if not (dest.parent / link).resolve().is_relative_to(base):
                    raise ValueError(link)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.unlink(missing_ok=True)
                dest.symlink_to(link)
                continue
            z.extract(entry, base)
            if mode & 0o111:
                os.chmod(base / entry.filename, mode & 0o777)


def github(repo, suffix, target):
    release = json.loads((DL / (repo.split("/")[-1] + "-release.json")).read_text())
    asset = next(a for a in release["assets"] if a["name"].endswith(suffix))
    digest = asset.get("digest", "")
    checksum = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
    archive = fetch(asset["browser_download_url"], asset["name"], checksum)
    if suffix.endswith(".jar"):
        shutil.copy2(archive, ROOT / target)
    else:
        unzip(archive, ROOT / target)


def android(package, metadata, target):
    root = ET.fromstring((DL / metadata).read_bytes())
    packages = [p for p in root.findall("remotePackage") if p.get("path") == package]
    package_node = next(
        (
            p
            for p in packages
            if p.find("channelRef") is None
            or p.find("channelRef").get("ref") == "channel-0"
        ),
        packages[0],
    )
    ar = next(
        a
        for a in package_node.findall("./archives/archive")
        if a.findtext("host-os") in [None, "linux"]
    )
    complete = ar.find("complete")
    url = complete.findtext("url")
    base = "https://dl.google.com/android/repository/"
    if metadata == "images.xml":
        base += "sys-img/android/"
    checksum = complete.find("checksum")
    archive = fetch(
        base + url, url.split("/")[-1], checksum.text, checksum.get("type", "sha1")
    )
    unzip(archive, ROOT / target)


def jdk():
    release = get_json(
        "https://api.github.com/repos/adoptium/temurin21-binaries/releases/latest"
    )
    p = next(
        a
        for a in release["assets"]
        if a["name"].startswith("OpenJDK21U-jdk_x64_linux_hotspot_")
        and a["name"].endswith(".tar.gz")
    )
    sha_asset = next(
        a for a in release["assets"] if a["name"] == p["name"] + ".sha256.txt"
    )
    checksum = (
        urllib.request.urlopen(sha_asset["browser_download_url"], timeout=TIMEOUT)
        .read()
        .decode()
        .split()[0]
    )
    archive = fetch(p["browser_download_url"], p["name"], checksum)
    target = ROOT / "jdk"
    target.mkdir(exist_ok=True)
    with tarfile.open(archive) as t:
        t.extractall(target, filter="data")


JOBS = [
    (jdk, ()),
    (github, ("iBotPeaches/Apktool", ".jar", "apktool.jar")),
    (github, ("skylot/jadx", "jadx-1.5.6.zip", "jadx")),
    (github, ("NationalSecurityAgency/ghidra", ".zip", "ghidra")),
    (android, ("platform-tools", "sdk.xml", "sdk")),
    (android, ("emulator", "sdk.xml", "sdk")),
    (android, ("build-tools;35.0.0", "sdk.xml", "sdk/build-tools")),
    (android, ("platforms;android-35", "sdk.xml", "sdk/platforms")),
    (android, ("ndk;27.2.12479018", "sdk.xml", "sdk/ndk")),
    (
        android,
        (
            "system-images;android-30;default;x86_64",
            "images.xml",
            "sdk/system-images/android-30/default",
        ),
    ),
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--components",
        choices=["build", "all"],
        default="build",
        help="Default: build tools; all adds Ghidra/JADX and the Android emulator",
    )
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    metadata()
    if args.metadata_only:
        raise SystemExit(0)
    jobs = JOBS
    if args.components == "build":
        jobs = [
            (fn, values)
            for fn, values in JOBS
            if fn == jdk
            or (fn == github and values[0] == "iBotPeaches/Apktool")
            or (
                fn == android
                and values[0]
                not in ["emulator", "system-images;android-30;default;x86_64"]
            )
        ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(fn, *values): (fn.__name__, values) for fn, values in jobs
        }
        errors = []
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
                print("installed", futures[future], flush=True)
            except Exception as e:
                errors.append((futures[future], str(e)))
                print("ERROR", futures[future], e, flush=True)
        if errors:
            raise SystemExit(1)
