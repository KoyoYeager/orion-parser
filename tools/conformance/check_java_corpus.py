"""Check entire OpenJDK modules for syntax acceptance and compilation-unit structure."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from zipfile import ZipFile

from check_java_modules import ROOT, project, read_reference, source_archive
from orionparser.registry import get_pipeline


def unit_surface(unit):
    types = []
    for decl in unit["declarations"]:
        kind = decl["type"].removesuffix("Declaration").upper()
        kind = {"ANNOTATIONINTERFACE": "ANNOTATION_TYPE", "EMPTY": "EMPTY_STATEMENT"}.get(kind, kind)
        types.append({"kind": kind, "name": decl.get("name")})
    module = unit["module"]
    return {
        "package": unit["package"]["name"] if unit["package"] else None,
        "types": types,
        "imports": [[i["static"], i["name"] + (".*" if i["onDemand"] else "")] for i in unit["imports"]],
        "module": module["name"] if module else None,
        "open": bool(module and module["open"]),
        "directives": [project(d) for d in module["directives"]] if module else [],
        "annotations": [a["name"] for a in module["annotations"]] if module else [],
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--jdk", type=Path, default=ROOT / ".venv/toolchains/jdk-21.0.2")
    cli.add_argument("--source-zip", type=Path, help="pinned OpenJDK source archive for an alternate JDK installation")
    group = cli.add_mutually_exclusive_group()
    group.add_argument("--module", action="append", help="OpenJDK module to check (default java.base)")
    group.add_argument("--all", action="store_true", help="check all modules in the pinned source archive")
    args = cli.parse_args()
    archive = source_archive(args.jdk, args.source_zip)
    failures = 0
    with tempfile.TemporaryDirectory() as directory, ZipFile(archive) as sources:
        stage = Path(directory)
        requested = set(args.module or ["java.base"])
        names = sorted(n for n in sources.namelist() if n.endswith(".java") and (args.all or n.split("/")[0] in requested))
        modules = {n.split("/")[0] for n in names}
        if not args.all and requested != modules:
            raise ValueError(f"unknown modules: {requested-modules}")
        subprocess.run([args.jdk / "bin/javac", "-d", stage, ROOT / "tools/conformance/JavaParseOracle.java"], check=True)
        for start in range(0, len(names), 192):
            paths = []
            for name in names[start:start+192]:
                path = stage / name
                path.parent.mkdir(exist_ok=True, parents=True)
                path.write_bytes(sources.read(name))
                paths.append(path)
            refs = read_reference(args.jdk, stage, paths, surface=True)
            for path, ref in zip(paths, refs, strict=True):
                result = get_pipeline(path).analyze_file(path)
                if not result.success or not ref["accepted"]:
                    print(f"{path.relative_to(stage)}: Orion {result.errors}; javac {ref['errors']}", flush=True)
                    failures += 1
                else:
                    for key, value in unit_surface(result.ast).items():
                        if value != ref[key]:
                            print(f"{path.relative_to(stage)}: {key}: Orion {value!r}, javac {ref[key]!r}", flush=True)
                            failures += 1
                            break
                path.unlink()
    print(f"{len(names)-failures}/{len(names)} compilation units matched javac in {len(modules)} modules")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
