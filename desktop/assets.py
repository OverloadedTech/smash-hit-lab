"""Read the shipped XML/mesh/MTX formats without modifying the input APK."""

from pathlib import Path
from functools import lru_cache
import hashlib, io, json, math, struct, zipfile, zlib
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
KNOWN_APK = "3b2ffa02fee8ca762f40648f1a9bec5c308764e881dd6a79cacd6dccdb16e338"
VERTEX = np.dtype([("p", "<f4", (3,)), ("uv", "<f4", (2,)), ("c", "u1", (4,))])


def vector(value, default=(0, 0, 0)):
    if value is None:
        value = default
    if isinstance(value, str):
        value = value.split()
    result = [float(v) for v in value]
    if len(result) != 3 or not all(math.isfinite(v) and abs(v) <= 1e7 for v in result):
        raise ValueError("Expected three finite coordinates")
    return result


def rotation(degrees):
    x, y, z = np.radians(vector(degrees))
    cx, cy, cz = np.cos([x, y, z])
    sx, sy, sz = np.sin([x, y, z])
    return (
        np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        @ np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
        @ np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    )


def quaternion(degrees):
    x, y, z = np.radians(vector(degrees)) / 2
    cx, cy, cz = np.cos([x, y, z])
    sx, sy, sz = np.sin([x, y, z])
    return [
        float(cy * sx * cz + sy * cx * sz),
        float(sy * cx * cz - cy * sx * sz),
        float(cy * cx * sz - sy * sx * cz),
        float(cy * cx * cz + sy * sx * sz),
    ]


class Assets:
    def __init__(self, apk):
        self.apk = Path(apk).resolve()
        self.sha256 = hashlib.sha256(self.apk.read_bytes()).hexdigest()
        self.archive = zipfile.ZipFile(self.apk)
        self.names = set(self.archive.namelist())
        self.templates = {
            e.attrib["name"]: dict(e.find("properties").attrib)
            for e in ET.fromstring(self.read("templates.xml"))
            if e.tag == "template"
        }
        self.segments = {}
        for name in sorted(self.names):
            if not name.startswith("assets/segments/") or not name.endswith(".xml.mp3"):
                continue
            key = name[len("assets/segments/") : -8]
            root = ET.fromstring(self.archive.read(name))
            size = vector(root.get("size"))
            if size[2] <= 0:
                raise ValueError(f"Segment has no positive physical length: {key}")
            self.segments[key] = {
                "path": key,
                "size": size,
                "length": size[2],
                "boxes": sum(e.tag == "box" for e in root),
                "objects": len(root),
                "attributes": dict(root.attrib),
            }

    def read(self, logical):
        for suffix in (".mp3", ""):
            path = "assets/" + logical + suffix
            if path in self.names:
                return self.archive.read(path)
        raise FileNotFoundError(logical)

    def require(self, key):
        if key not in self.segments:
            raise ValueError("Unknown segment")

    @lru_cache(maxsize=48)
    def mesh(self, key):
        self.require(key)
        data = zlib.decompress(self.read("segments/" + key + ".mesh"))
        (nv,) = struct.unpack_from("<I", data)
        end = 4 + nv * 24
        (nt,) = struct.unpack_from("<I", data, end)
        if len(data) != end + 4 + 12 * nt:
            raise ValueError("Invalid mesh length")
        vertices = np.frombuffer(data, dtype=VERTEX, count=nv, offset=4)
        triangles = np.frombuffer(
            data, dtype="<u4", count=nt * 3, offset=end + 4
        ).reshape(-1, 3)
        if not np.isfinite(vertices["p"]).all() or (nt and triangles.max() >= nv):
            raise ValueError("Invalid mesh vertices/indices")
        return data, vertices, triangles

    @lru_cache(maxsize=80)
    def metadata(self, key):
        self.require(key)
        xml = self.read("segments/" + key + ".xml").decode("utf-8-sig")
        root = ET.fromstring(xml)
        base = (ROOT / "dev/assets/shdev/geometry").resolve()
        cached = (base / (key + ".json")).resolve()
        if not cached.is_relative_to(base):
            raise ValueError("Unsafe segment name")
        if self.sha256 == KNOWN_APK and cached.exists():
            mapping = json.loads(cached.read_text())
        else:
            mapping = self.map_geometry(key, root)
        records = [
            {"source_index": i, "type": e.tag, "attributes": dict(e.attrib)}
            for i, e in enumerate(root)
            if e.tag != "box"
        ]
        return dict(self.segments[key], mapping=mapping, records=records, xml=xml)

    def map_geometry(self, key, root):
        _, vertices, triangles = self.mesh(key)
        nv = len(vertices)
        if nv % 4 or len(triangles) * 2 != nv:
            raise ValueError("Unsupported non-quad baked mesh")
        quads = vertices["p"].reshape(-1, 4, 3)
        nq = len(quads)
        normals = np.zeros((nq, 3), np.float32)
        if len(triangles):
            tri = vertices["p"][triangles]
            normals[triangles[:, 0] // 4] = np.cross(
                tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
            )
        qmin = quads.min(axis=1)
        qmax = quads.max(axis=1)
        owners = np.full(nq, -1, dtype=np.int32)
        matches = np.zeros(nq, dtype=np.int32)
        boxes = []
        eps = 2e-4
        for index, node in enumerate(root):
            if node.tag != "box":
                continue
            attr = dict(self.templates.get(node.get("template"), {}))
            attr.update(node.attrib)
            pos = np.array(vector(attr.get("pos")))
            half = np.array(vector(attr.get("size"), (1, 1, 1)))
            box = {
                "source_index": index,
                "ordinal": len(boxes),
                "position": pos.tolist(),
                "half_extents": half.tolist(),
                "hidden": attr.get("hidden", "0") != "0",
                "attributes": attr,
                "quads": [],
                "ambiguous": False,
            }
            if not box["hidden"]:
                lo, hi = pos - half, pos + half
                inside = np.all(qmin >= lo - eps, axis=1) & np.all(
                    qmax <= hi + eps, axis=1
                )
                face = np.zeros(nq, dtype=bool)
                for axis in range(3):
                    face |= (
                        (np.abs(qmin[:, axis] - hi[axis]) < eps)
                        & (np.abs(qmax[:, axis] - hi[axis]) < eps)
                        & (normals[:, axis] > 1e-7)
                    )
                    face |= (
                        (np.abs(qmin[:, axis] - lo[axis]) < eps)
                        & (np.abs(qmax[:, axis] - lo[axis]) < eps)
                        & (normals[:, axis] < -1e-7)
                    )
                ids = np.flatnonzero(inside & face)
                box["quads"] = ids.tolist()
                matches[ids] += 1
                owners[ids] = len(boxes)
            boxes.append(box)
        for box in boxes:
            box["ambiguous"] = any(matches[q] > 1 for q in box["quads"])
            box["editable"] = bool(box["quads"]) and not box["ambiguous"]
        owners[matches != 1] = -1
        return {
            "version": 1,
            "source": "segments/" + key + ".xml",
            "mesh": "segments/" + key + ".mesh",
            "vertex_count": nv,
            "boxes": boxes,
            "owners": owners.tolist(),
        }

    @lru_cache(maxsize=1)
    def texture(self):
        data = self.read("gfx/tiles.png.mtx")
        kind, size, reserved = struct.unpack_from("<III", data)
        if size != len(data) - 12 or reserved:
            raise ValueError("Invalid MTX")
        if kind == 0:
            image = Image.open(io.BytesIO(data[12:])).convert("RGBA")
        elif kind == 1:
            version, width, height, n = struct.unpack_from("<4I", data, 12)
            if version != 1:
                raise ValueError("Invalid MTX version")
            image = Image.open(io.BytesIO(data[28 : 28 + n])).convert("RGBA")
            alpha = zlib.decompress(data[32 + n :])
            if len(alpha) != width * height or image.size != (width, height):
                raise ValueError("Invalid alpha plane")
            image.putalpha(Image.frombytes("L", (width, height), alpha))
        else:
            raise ValueError("Unsupported MTX type")
        result = io.BytesIO()
        image.save(result, format="PNG")
        return result.getvalue()

    def catalog(self):
        return {
            "format": "smash-hit-lab-catalog-v1",
            "apk_sha256": self.sha256,
            "segments": list(self.segments.values()),
            "count": len(self.segments),
            "notice": "Original baked geometry. Obstacle scripts and game physics do not run in this editor.",
        }

    def validate_project(self, project):
        if (
            not isinstance(project, dict)
            or project.get("format") != "smash-hit-lab-project-v1"
        ):
            raise ValueError("Not a Smash Hit Lab project")
        if project.get("apk_sha256") != self.sha256:
            raise ValueError("Project requires a different input APK")
        if (
            not isinstance(project.get("segments"), list)
            or len(project["segments"]) > 5000
        ):
            raise ValueError("Invalid segment list")
        seen = set()
        result = {
            "format": project["format"],
            "apk_sha256": self.sha256,
            "name": str(project.get("name", "Untitled"))[:160],
            "segments": [],
        }
        for item in project["segments"]:
            self.require(item["source"])
            identity = str(item["id"])
            if identity in seen:
                raise ValueError("Duplicate instance ID")
            seen.add(identity)
            node = {
                "id": identity,
                "source": item["source"],
                "position": vector(item.get("position")),
                "rotation": vector(item.get("rotation")),
                "scale": vector(item.get("scale"), (1, 1, 1)),
                "edits": {},
            }
            if any(v < 0.01 or v > 100 for v in node["scale"]):
                raise ValueError("Scale must be between 0.01 and 100")
            if item.get("edits"):
                boxes = self.metadata(item["source"])["mapping"]["boxes"]
                for key, edit in item["edits"].items():
                    i = int(key)
                    if i < 0 or i >= len(boxes) or not boxes[i]["editable"]:
                        raise ValueError(
                            "This box has no unambiguous render-face mapping"
                        )
                    value = {
                        "position": vector(edit["position"]),
                        "rotation": vector(edit["rotation"]),
                        "scale": vector(edit["scale"]),
                    }
                    if any(v < 0.01 or v > 100 for v in value["scale"]):
                        raise ValueError("Invalid box scale")
                    node["edits"][str(i)] = value
            result["segments"].append(node)
        return result

    def positions(self, item):
        _, vertices, _ = self.mesh(item["source"])
        p = vertices["p"].copy()
        if item["edits"]:
            boxes = self.metadata(item["source"])["mapping"]["boxes"]
            for key, e in item["edits"].items():
                b = boxes[int(key)]
                ids = (np.array(b["quads"])[:, None] * 4 + np.arange(4)).ravel()
                p[ids] = ((vertices["p"][ids] - b["position"]) * e["scale"]) @ rotation(
                    e["rotation"]
                ).T + e["position"]
        return p

    def stitch_catalog(self):
        z = 0
        items = []
        for i, entry in enumerate(self.segments.values()):
            items.append(
                {
                    "id": f"catalog-{i}",
                    "source": entry["path"],
                    "position": [0, 0, z],
                    "rotation": [0, 0, 0],
                    "scale": [1, 1, 1],
                    "edits": {},
                }
            )
            z -= entry["length"]
        return {
            "format": "smash-hit-lab-project-v1",
            "apk_sha256": self.sha256,
            "name": "All segments: catalogue order, not a generated playthrough",
            "segments": items,
        }
