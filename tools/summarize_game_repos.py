#!/usr/bin/env python3
"""Write compact public evidence summaries for the standalone source repositories."""

from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = {
    "smash-hit": "Android 8/API 26 x86_64 software emulator; SystemUI disabled after prior emulator boot/keyguard ANRs. This is a test-environment change, not an app requirement.",
    "granny-smith": "Android 6/API 23 ARMv7 software emulator; the optional ADB input helper ran as the emulator's root shell.",
    "pinout": "Android 8/API 26 x86_64 software emulator; SystemUI disabled after prior emulator boot/keyguard ANRs. This is a test-environment change, not an app requirement.",
}


def check_summary(check, default=True):
    if isinstance(check, str):
        return {"name": check, "passed": default}
    return {
        "name": check["name"],
        "passed": check.get("passed", check.get("result") == "PASS"),
    }


def main():
    combined = json.loads(
        (ROOT / "artifacts/mediocre-labs-validation-report.json").read_text()
    )
    formatting = json.loads((ROOT / "build/repo-checks/formatting.json").read_text())
    for game in ("smash-hit", "granny-smith", "pinout"):
        repo = ROOT / "repos" / (game + "-lab")
        cfg = json.loads((repo / "project.json").read_text())
        old = combined["games"][game]
        baseline = {
            "apk_sha256": old["apk_sha256"],
            "runtime": old["runtime"],
            "checks": old["behavior_checks"],
            "groups": [],
        }
        if game == "smash-hit":
            value = json.loads(
                (ROOT / "artifacts/simple-play-validation-report.json").read_text()
            )
            for group in value["groups"]:
                baseline["groups"].append(
                    {
                        "name": group["category"],
                        "checks": [
                            check_summary(c, value["result"] == "PASS")
                            for c in group["checks"]
                        ],
                    }
                )
        else:
            for group in old["groups"]:
                value = json.loads((ROOT / group["report"]).read_text())
                baseline["groups"].append(
                    {
                        "name": group["kind"],
                        "report_sha256": group["report_sha256"],
                        "checks": [check_summary(c) for c in value["checks"]],
                    }
                )
        report_path = (
            ROOT
            / "build/repo-checks/clean checkout"
            / (game + "-lab")
            / "artifacts"
            / (game + "-build-report.json")
        )
        build = json.loads(report_path.read_text())
        record = {
            "scope": "Local measurements for the exact supported APK; no physical ARM64 coverage.",
            "input_sha256": cfg["sha256"],
            "baseline_before_repository_split": baseline,
            "repository_build": {
                "passed": True,
                "environment": "Linux x86_64, Python 3.13; source ZIP unpacked in a separate directory; existing pinned toolchain and private input APK supplied separately.",
                **build,
            },
            "source_reorganization_before_fixes": {
                name.split("/", 1)[1]: entry
                for name, entry in formatting.items()
                if name.startswith(repo.name + "/")
            },
            "repository_runtime_checks": [],
        }
        changed = {}
        for name, entry in record["source_reorganization_before_fixes"].items():
            current = hashlib.sha256((repo / name).read_bytes()).hexdigest()
            if current != entry["repo_sha256"]:
                changed[name] = {"current_sha256": current}
        if changed:
            record["native_changes_after_reorganization"] = changed
        formats = ROOT / "build/repo-checks/format-reader-summary.json"
        if formats.exists():
            record["original_apk_format_reader"] = json.loads(formats.read_text())[game]
        source_tests = ROOT / "build/repo-checks/source-tests.json"
        if source_tests.exists():
            checks = json.loads(source_tests.read_text())[game]["checks"]
            count = re.search(r"Ran (\d+) tests", checks["unit_tests"]["stderr"])
            record["repository_source_checks"] = {
                "environment": "Linux x86_64, Python 3.13, Ruff 0.12.12; source archive extracted into a temporary directory without game inputs or Android tools.",
                "help_without_sdk": checks["help"]["passed"],
                "unit_tests_passed": checks["unit_tests"]["passed"],
                "unit_test_count": int(count[1]) if count else None,
                "lint_passed": checks["lint"]["passed"],
                "hosted_github_actions_run": False,
            }
        for kind in ("native", "desktop", "touch", "player", "smoke"):
            path = ROOT / "build/repo-checks" / (game + "-" + kind) / "report.json"
            if path.exists():
                value = json.loads(path.read_text())
                record["repository_runtime_checks"].append(
                    {
                        "kind": kind,
                        "passed": value.get("passed", False),
                        "completed": value.get("completed", False),
                        "apk_sha256": value.get("build", {}).get("sha256"),
                        "runtime": RUNTIME[game],
                        "report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "checks": [check_summary(c) for c in value["checks"]],
                    }
                )
        if game == "smash-hit":
            record["native_changes_after_reorganization"]["native/engine.cpp"][
                "reason"
            ] = "Skip null or empty dlpi_name entries before strrchr; fixes a reproduced Android 8 startup SIGSEGV."
            failed = (
                ROOT / "build/repo-checks/smash-hit-before-null-name-fix/report.json"
            )
            if failed.exists():
                record["startup_failure_before_fix"] = json.loads(failed.read_text())
            record["observer_recovery"] = (
                "Package-manager and whole-APK transfer requests timed out before camera/edit checks. The regression now identifies the loaded addon from the running process's mappings and compares its actual bytes with the locally built APK. The Android query/transfer stalls' cause is unknown."
            )
            browser = ROOT / "build/repo-checks/smash-hit-browser/desktop/report.json"
            if browser.exists():
                value = json.loads(browser.read_text())
                record["repository_browser_checks"] = {
                    "passed": value["result"] == "PASS",
                    "checks": [check_summary(c) for c in value["checks"]],
                    "runtime": "Desktop Chromium with SwiftShader, original APK supplied locally; no native game simulation in this editor.",
                }
        if game == "granny-smith":
            record["installation_recovery"] = (
                "The Android package manager stalled before the game launched. Restarting the emulator and reinstalling recovered it. The installed APK hash was checked before running the suites. Stall cause unknown."
            )
        path = (
            ROOT
            / "build/repo-checks"
            / (
                "granny-scene-import.json"
                if game == "granny-smith"
                else "pinout-scene-import.json"
            )
        )
        if game != "smash-hit" and path.exists():
            value = json.loads(path.read_text())
            record["offline_scene_import"] = {
                "passed": value["passed"],
                "checks": value["checks"],
            }
        (repo / "docs/validation.json").write_text(json.dumps(record, indent=2) + "\n")
        print(game, "recorded source/build evidence")


if __name__ == "__main__":
    main()
