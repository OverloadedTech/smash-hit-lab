#!/usr/bin/env python3
"""Local desktop editor. Run: python -m desktop.server --apk com.smash.hit.apk"""

from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import argparse, json, mimetypes, re, threading
import struct, subprocess, zlib
from .assets import Assets
from .export import glb

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "desktop/web"
PROJECTS = ROOT / "desktop/projects"


class Handler(BaseHTTPRequestHandler):
    def local_host(self):
        return self.headers.get("Host") in {
            "127.0.0.1:" + str(self.server.server_port),
            "localhost:" + str(self.server.server_port),
        }

    def send(self, data, status=200, kind="application/json", filename=None):
        if isinstance(data, (dict, list)):
            data = json.dumps(data, separators=(",", ":")).encode()
        if isinstance(data, str):
            data = data.encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if filename:
            self.send_header(
                "Content-Disposition", 'attachment; filename="' + filename + '"'
            )
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        if len(args) < 2 or not str(args[1]).isdigit() or int(args[1]) >= 400:
            super().log_message(format, *args)

    def project_path(self, name):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.json", name):
            raise ValueError("Use a simple .json project filename")
        return PROJECTS / name

    def do_GET(self):
        if not self.local_host():
            return self.send({"error": "Use the local editor address"}, 403)
        try:
            u = urlparse(self.path)
            q = parse_qs(u.query)
            a = self.server.assets
            if u.path == "/api/catalog":
                return self.send(a.catalog())
            if u.path == "/api/segment":
                return self.send(a.metadata(q["path"][0]))
            if u.path == "/api/mesh":
                return self.send(
                    a.mesh(q["path"][0])[0], kind="application/octet-stream"
                )
            if u.path == "/api/texture":
                return self.send(a.texture(), kind="image/png")
            if u.path == "/api/runtime":
                from .runtime import connected

                a.require(q["path"][0])
                return self.send(connected(q["path"][0]))
            if u.path == "/api/stitch-catalog":
                return self.send(a.stitch_catalog())
            if u.path == "/api/projects":
                return self.send(sorted(p.name for p in PROJECTS.glob("*.json")))
            if u.path == "/api/project":
                return self.send(
                    json.loads(self.project_path(q["name"][0]).read_text())
                )
            path = (
                WEB / ("index.html" if u.path == "/" else u.path.lstrip("/"))
            ).resolve()
            if not path.is_relative_to(WEB.resolve()) or not path.is_file():
                return self.send({"error": "Not found"}, 404)
            return self.send(
                path.read_bytes(),
                kind=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            )
        except (
            KeyError,
            ValueError,
            OSError,
            RuntimeError,
            struct.error,
            zlib.error,
            subprocess.SubprocessError,
        ) as e:
            return self.send({"error": str(e)}, 400)

    def do_POST(self):
        if not self.local_host():
            return self.send({"error": "Use the local editor address"}, 403)
        try:
            expected = "http://" + self.headers.get("Host", "")
            if self.headers.get("Origin", expected) != expected:
                raise ValueError("Cross-origin writes are disabled")
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > 8_000_000:
                raise ValueError("Invalid project request size")
            body = json.loads(self.rfile.read(n))
            a = self.server.assets
            if self.path == "/api/export":
                return self.send(
                    glb(a, body),
                    kind="model/gltf-binary",
                    filename="smash-hit-world.glb",
                )
            if self.path == "/api/validate":
                return self.send(a.validate_project(body))
            if self.path == "/api/runtime/apply":
                from .runtime import apply

                with self.server.runtime_lock:
                    return self.send(apply(a, body))
            if self.path == "/api/save":
                project = a.validate_project(body["project"])
                p = self.project_path(body["filename"])
                PROJECTS.mkdir(exist_ok=True)
                temp = p.with_suffix(".tmp")
                temp.write_text(json.dumps(project, indent=2) + "\n")
                temp.replace(p)
                return self.send({"saved": p.name})
            return self.send({"error": "Unknown command"}, 404)
        except (
            ValueError,
            KeyError,
            OSError,
            RuntimeError,
            TypeError,
            struct.error,
            zlib.error,
            subprocess.SubprocessError,
        ) as e:
            return self.send({"error": str(e)}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", type=Path, default=ROOT / "com.smash.hit.apk")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--stitch-all",
        type=Path,
        help="Export the complete segment catalogue to one GLB, then exit",
    )
    args = parser.parse_args()
    if not args.apk.is_file():
        raise SystemExit(f"No APK at {args.apk}. Supply your own copy with --apk.")
    assets = Assets(args.apk)
    if args.stitch_all:
        args.stitch_all.parent.mkdir(parents=True, exist_ok=True)
        args.stitch_all.write_bytes(glb(assets, assets.stitch_catalog()))
        print("Exported", len(assets.segments), "segments to", args.stitch_all)
        return
    if not (WEB / "vendor/three/build/three.module.js").exists():
        raise SystemExit("Run python tools/setup_desktop.py first")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.assets = assets
    server.runtime_lock = threading.Lock()
    print(
        f"Smash Hit Lab desktop editor: http://127.0.0.1:{args.port}: {len(assets.segments)} actual segments",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
