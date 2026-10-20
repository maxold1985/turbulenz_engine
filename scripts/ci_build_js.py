#!/usr/bin/env python3
"""Build legacy Turbulenz TypeScript core and examples on modern CI runners.

This is the JavaScript-only fallback, not the original CGFX/native toolchain.
It follows the original Makefile's 'crude' approach: compile each .ts source
with --noResolve and keep emitted JavaScript despite legacy type diagnostics.
"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sources(folder):
    """Return TypeScript implementation files, excluding .d.ts declarations."""
    return sorted(
        p for p in (ROOT / folder).rglob("*.ts")
        if p.is_file() and not p.name.endswith(".d.ts")
    )


def build_group(name, src_files, base, destination, compiler, log):
    """Compile every source independently, preserving the source tree layout."""
    results = []
    for index, source in enumerate(src_files, 1):
        relative = source.relative_to(ROOT / base)
        output = destination / relative.with_suffix(".js")
        output.parent.mkdir(parents=True, exist_ok=True)

        # --noResolve matches Turbulenz's legacy non-modular ("crude") Make rule.
        command = [
            compiler, "--noResolve", "--target", "ES5",
            "--out", str(output.relative_to(ROOT)),
            str(source.relative_to(ROOT)),
        ]
        proc = subprocess.run(command, cwd=ROOT, capture_output=True,
                              text=True, errors="replace")
        emitted = output.is_file() and output.stat().st_size > 0
        result = {
            "source": source.relative_to(ROOT).as_posix(),
            "javascript": output.relative_to(ROOT).as_posix() if emitted else None,
            "compiler_exit_code": proc.returncode,
            "emitted": emitted,
        }
        results.append(result)

        if proc.returncode or not emitted:
            log.write("\n$ " + " ".join(command) + "\n")
            log.write(proc.stdout + proc.stderr + "\n")
            log.flush()

        status = "JS" if emitted else "MISSING JS"
        if proc.returncode:
            status += " (type diagnostics)"
        print(f"[{name} {index}/{len(src_files)}] {status}: {relative.as_posix()}",
              flush=True)
    return results


def copy_legacy_resources(output):
    """Retain sources/assets needed for a later full shader/HTML package build."""
    for folder in ("css", "js", "images", "img", "icons", "templates", "tsscripts"):
        source = ROOT / "samples" / folder
        if source.is_dir():
            shutil.copytree(source, output / "examples" / "samples" / folder,
                            dirs_exist_ok=True)
    shader_source = ROOT / "assets" / "shaders"
    if shader_source.is_dir():
        shutil.copytree(shader_source, output / "core" / "assets" / "shaders",
                        dirs_exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="ci-output")
    args = parser.parse_args()

    output = (ROOT / args.output).resolve()
    try:
        output.relative_to(ROOT)
    except ValueError:
        parser.error("--output must be inside the repository")

    compiler = shutil.which("tsc")
    if not compiler:
        print("ERROR: tsc is unavailable. Install typescript@1.0.1.", file=sys.stderr)
        return 2

    output.mkdir(parents=True, exist_ok=True)
    log_path = output / "typescript-diagnostics.log"
    core_files = sources("tslib")
    example_files = sources("samples/tsscripts")

    # Include runnable app TypeScript sources and protolib examples when present.
    app_files = sources("apps")
    proto_files = sources("protolib")

    with log_path.open("w", encoding="utf-8") as log:
        version = subprocess.run([compiler, "--version"], cwd=ROOT,
                                 capture_output=True, text=True, errors="replace")
        log.write("TypeScript version: " + version.stdout + version.stderr + "\n")
        core = build_group("core", core_files, "tslib",
                           output / "core" / "jslib", compiler, log)
        examples = build_group("samples", example_files, "samples/tsscripts",
                               output / "examples" / "js" / "samples", compiler, log)
        apps = build_group("apps", app_files, "apps",
                           output / "examples" / "js" / "apps", compiler, log)
        protolib = build_group("protolib", proto_files, "protolib",
                               output / "examples" / "js" / "protolib", compiler, log)

    copy_legacy_resources(output)
    groups = {"core": core, "samples": examples, "apps": apps, "protolib": protolib}
    required = [
        output / "core/jslib/debug.js",
        output / "core/jslib/vmath.js",
        output / "examples/js/samples/templates/basic_loop.js",
        output / "examples/js/samples/templates/device_initialization.js",
    ]
    missing = [str(p.relative_to(output)) for p in required if not p.is_file()]
    missing_all = [r["source"] for group in groups.values() for r in group
                   if not r["emitted"]]
    report = {
        "compiler": version.stdout.strip() or version.stderr.strip(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "groups": {
            name: {
                "sources": len(items),
                "javascript_emitted": sum(x["emitted"] for x in items),
                "compiler_diagnostics": sum(x["compiler_exit_code"] != 0
                                            for x in items),
            }
            for name, items in groups.items()
        },
        "missing_javascript": missing_all,
        "missing_required": missing,
        "type": "legacy TypeScript JavaScript-only source build",
        "native_tools_compiled": False,
        "cgfx_compiled": False,
        "html_samples_packaged_as_runnable": False,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    note = (
        "TURBULENZ LEGACY JAVASCRIPT BUILD\n"
        "core/jslib/: JavaScript emitted from tslib TypeScript sources.\n"
        "examples/js/samples/: JavaScript emitted from sample templates and helpers.\n"
        "examples/js/apps/: JavaScript emitted from app sources.\n"
        "examples/samples/: original example templates and resource files.\n"
        "core/assets/shaders/: ORIGINAL CgFX shader sources, not compiled JSON.\n"
        "\nIMPORTANT: This is a JS-only compatibility build, not the original\n"
        "complete native/shader pipeline or playable HTML5 demo package.\n"
        "The old CgFX converter, Python 2.7 tools and sample HTML packager\n"
        "remain necessary for the original full release build.\n"
        "Inspect report.json and typescript-diagnostics.log for details.\n"
    )
    (output / "README.txt").write_text(note, encoding="utf-8")
    (output / "core" / "README.txt").write_text(note, encoding="utf-8")
    (output / "examples" / "README.txt").write_text(note, encoding="utf-8")

    print("\nBuild report:")
    print(json.dumps(report["groups"], indent=2))
    if missing_all or missing:
        print("ERROR: Some source files did not emit JavaScript:", missing_all[:25],
              file=sys.stderr)
        print("Missing required outputs:", missing, file=sys.stderr)
        return 1
    if not core_files or not example_files:
        print("ERROR: Core or sample sources missing", file=sys.stderr)
        return 1
    print("JavaScript core and example sources generated (shader pipeline excluded).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
