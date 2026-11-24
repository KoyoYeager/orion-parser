"""Check pinned langtools source inputs using the parse phase only (no jtreg execution)."""
import argparse
import csv
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.request import urlopen

from check_java_corpus import unit_surface
from check_java_modules import ROOT, read_reference
from orionparser.registry import get_pipeline


REVISION = "375769c6986866210a0f36aad580e3ac8e9eb068"
BASE = f"https://raw.githubusercontent.com/openjdk/jdk21u/{REVISION}/test/langtools/tools/javac/"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("directory", type=Path)
    cli.add_argument("--fetch", action="store_true", help="download missing fixtures at the pinned revision")
    cli.add_argument("--jdk", type=Path, default=ROOT / ".venv/toolchains/jdk-21.0.2")
    args = cli.parse_args()
    with (ROOT / "docs/conformance/java-javac-tests.tsv").open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    paths = []
    for row in rows:
        path = args.directory / row["path"]
        if args.fetch and not path.exists():
            with urlopen(BASE + row["path"], timeout=30) as response:
                source = response.read()
            if hashlib.sha256(source).hexdigest() != row["sha256"]:
                raise ValueError(f"unexpected download digest: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source)
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"unexpected fixture digest: {path}")
        paths.append(path)
    accepted = rejected = differences = 0
    with tempfile.TemporaryDirectory() as folder:
        stage = Path(folder)
        subprocess.run([args.jdk/"bin/javac", "-d", stage, ROOT/"tools/conformance/JavaParseOracle.java"], check=True)
        refs = read_reference(args.jdk, stage, paths, surface=True)
        for path, row, ref in zip(paths, rows, refs, strict=True):
            result = get_pipeline(path).analyze_file(path)
            o = j = "accept"
            if not result.success:
                position = re.match(r"line (\d+), column (\d+):", result.errors[0])
                if not position:
                    raise ValueError(f"{path}: missing error position {result.errors}")
                o = ":".join(position.groups())
            if not ref["accepted"]:
                first = ref["errors"][0]
                j = f"{first['line']}:{first['column']}"
                if first["code"] != row["diagnostic"]:
                    raise ValueError(f"{path}: unexpected javac diagnostic {first}")
            if (o, j) != (row["orion"], row["javac"]):
                raise ValueError(f"{path}: unexpected Orion {o}, javac {j}")
            if o == j == "accept":
                if any(value != ref[key] for key, value in unit_surface(result.ast).items()):
                    raise ValueError(f"{path}: unit shape differs")
                accepted += 1
            elif (o == "accept") == (j == "accept"):
                rejected += 1
            elif row["difference"]:
                differences += 1
            else:
                raise ValueError(f"{path}: unclassified difference")
    print(f"{len(paths)} pinned langtools inputs: {accepted} matching units, {rejected} paired rejections, {differences} classified differences")


if __name__ == "__main__":
    main()
