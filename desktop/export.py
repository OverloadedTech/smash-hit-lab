"""Write one self-contained glTF binary from real segment meshes and editor edits."""

import json, struct
import numpy as np
from .assets import VERTEX, quaternion


def glb(assets, project):
    project = assets.validate_project(project)
    doc = {
        "asset": {"version": "2.0", "generator": "Smash Hit Lab research editor"},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "buffers": [{"byteLength": 0}],
        "bufferViews": [],
        "accessors": [],
        "extensionsUsed": ["KHR_materials_unlit"],
        "materials": [
            {
                "name": "Original tile atlas and baked vertex lighting",
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicFactor": 0,
                    "roughnessFactor": 1,
                },
                "doubleSided": True,
                "extensions": {"KHR_materials_unlit": {}},
            }
        ],
        "textures": [{"source": 0, "sampler": 0}],
        "samplers": [
            {"wrapS": 10497, "wrapT": 10497, "magFilter": 9729, "minFilter": 9729}
        ],
        "images": [],
        "extras": {
            "shlab_project": project,
            "scope": "Static baked geometry. Lua objects, physics, game fog and removed baked faces are not reconstructed.",
        },
    }
    chunks = []
    length = 0

    def view(data, target=None, stride=None):
        nonlocal length
        padding = (-length) % 4
        if padding:
            chunks.append(b"\0" * padding)
            length += padding
        i = len(doc["bufferViews"])
        v = {"buffer": 0, "byteOffset": length, "byteLength": len(data)}
        if target:
            v["target"] = target
        if stride:
            v["byteStride"] = stride
        doc["bufferViews"].append(v)
        chunks.append(data)
        length += len(data)
        return i

    def accessor(v, offset, component, count, kind, **extra):
        i = len(doc["accessors"])
        doc["accessors"].append(
            dict(
                bufferView=v,
                byteOffset=offset,
                componentType=component,
                count=count,
                type=kind,
                **extra
            )
        )
        return i

    png = assets.texture()
    doc["images"].append({"bufferView": view(png), "mimeType": "image/png"})
    for item in project["segments"]:
        _, source, indices = assets.mesh(item["source"])
        p = assets.positions(item)
        if not len(p):
            continue
        vertices = np.empty(len(source), dtype=VERTEX)
        vertices["p"] = p
        vertices["uv"] = source["uv"]
        shadow = source["c"][:, 3].astype(np.float32) / 255
        rgb = (
            source["c"][:, :3].astype(np.float32) * 2 * (1 - (1 - shadow[:, None]) ** 2)
        )
        vertices["c"][:, :3] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
        vertices["c"][:, 3] = 255
        v = view(vertices.tobytes(), 34962, 24)
        attributes = {
            "POSITION": accessor(
                v,
                0,
                5126,
                len(p),
                "VEC3",
                min=p.min(axis=0).tolist(),
                max=p.max(axis=0).tolist(),
            ),
            "TEXCOORD_0": accessor(v, 12, 5126, len(p), "VEC2"),
            "COLOR_0": accessor(v, 20, 5121, len(p), "VEC3", normalized=True),
        }
        iv = view(indices.tobytes(), 34963)
        a = accessor(iv, 0, 5125, indices.size, "SCALAR")
        mesh = len(doc["meshes"])
        doc["meshes"].append(
            {
                "name": item["source"],
                "primitives": [{"attributes": attributes, "indices": a, "material": 0}],
            }
        )
        node = len(doc["nodes"])
        doc["nodes"].append(
            {
                "name": item["id"] + " " + item["source"],
                "mesh": mesh,
                "translation": item["position"],
                "rotation": quaternion(item["rotation"]),
                "scale": item["scale"],
                "extras": {
                    "source": "segments/" + item["source"] + ".xml",
                    "instance_id": item["id"],
                    "box_edits": item["edits"],
                },
            }
        )
        doc["scenes"][0]["nodes"].append(node)
    doc["buffers"][0]["byteLength"] = length
    binary = b"".join(chunks)
    binary += b"\0" * ((-len(binary)) % 4)
    text = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    text += b" " * ((-len(text)) % 4)
    return (
        struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(text) + 8 + len(binary))
        + struct.pack("<II", len(text), 0x4E4F534A)
        + text
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )
