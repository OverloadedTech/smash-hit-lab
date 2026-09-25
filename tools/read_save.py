#!/usr/bin/env python3
"""Read native save XML using the key from the user's local APK. Never writes saves."""

from pathlib import Path
from io import BytesIO
import argparse
import json
import struct
import sys
import zipfile
import xml.etree.ElementTree as ET
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection


def local_key(apk):
    with zipfile.ZipFile(apk) as archive:
        data = archive.read("lib/x86_64/libsmashhit.so")
    elf = ELFFile(BytesIO(data))

    def read(address, size):
        for segment in elf.iter_segments():
            if (
                segment["p_type"] == "PT_LOAD"
                and segment["p_vaddr"] <= address
                and address + size <= segment["p_vaddr"] + segment["p_filesz"]
            ):
                offset = segment["p_offset"] + address - segment["p_vaddr"]
                return data[offset : offset + size]
        raise ValueError("ELF address is outside file-backed segments")

    symbols = elf.get_section_by_name(".dynsym").get_symbol_by_name("encryptionKey")
    if not symbols:
        raise ValueError("This native library exposes no supported save key")
    address = symbols[0]["st_value"]
    target = None
    for section in elf.iter_sections():
        if not isinstance(section, RelocationSection):
            continue
        for relocation in section.iter_relocations():
            if relocation["r_offset"] == address and relocation["r_info_type"] == 8:
                target = relocation["r_addend"]
    if target is None:
        target = struct.unpack("<Q", read(address, 8))[0]
    key = bytearray()
    for index in range(1024):
        value = read(target + index, 1)[0]
        if value == 0:
            if not key:
                raise ValueError("Empty save key")
            return bytes(key)
        key.append(value)
    raise ValueError("Unterminated save key")


def decode_bytes(data, apk):
    """Return the exact XML bytes, including quirks of the native XML writer."""
    # Some original progression files contain repeated attributes. Do not repair
    # these, or mistake an already-plain native document for encrypted bytes.
    # clearQuickSave also writes a plain empty XML element.
    if data.lstrip().startswith(
        (b"<smashhit", b"<quicksave", b"<achievements", b"<config", b"<?xml")
    ):
        return data
    try:
        ET.fromstring(data)
        return data
    except ET.ParseError:
        key = local_key(apk)
        return bytes(
            (value - key[index % len(key)] - len(data)) & 255
            for index, value in enumerate(data)
        )


def decode(data, apk):
    """Parse a standards-conforming save without silently changing attributes."""
    return ET.fromstring(decode_bytes(data, apk))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("save", type=Path)
    parser.add_argument("--apk", type=Path, default=Path("com.smash.hit.apk"))
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print exact decoded XML bytes, preserving duplicate attributes",
    )
    args = parser.parse_args()
    plain = decode_bytes(args.save.read_bytes(), args.apk)
    if args.raw:
        sys.stdout.buffer.write(plain)
        return
    try:
        root = ET.fromstring(plain)
    except ET.ParseError as error:
        parser.exit(
            2,
            f"Decoded save is not strict XML: {error}. "
            "Use --raw to inspect its exact contents; no repair was applied.\n",
        )
    print(
        json.dumps(
            {
                "root": root.tag,
                "attributes": root.attrib,
                "children": [{"tag": e.tag, "attributes": e.attrib} for e in root],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
