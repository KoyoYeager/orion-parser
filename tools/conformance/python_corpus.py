"""Prepare the pinned source-only fixtures for Python language regression tests."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
from urllib.request import urlopen


def download_file(item):
    url, destination, expected = item
    if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == expected:
        return
    with urlopen(url, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Checksum mismatch for {url}")
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temp:
        temp.write(data)
    Path(temp.name).replace(destination)


def source_tree_digest(directory):
    digest = hashlib.sha256()
    for file in sorted(directory.rglob("*.py")):
        digest.update(file.relative_to(directory).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(file.read_bytes()).digest())
    return digest.hexdigest()


def prepare_archive(root, alias, entry):
    destination = root / alias
    url = f"https://codeload.github.com/{entry['repository']}/tar.gz/{entry['revision']}"
    marker = destination / ".revision"
    if marker.is_file() and marker.read_text() == entry["revision"] and source_tree_digest(destination) == entry["tree_sha256"]:
        return
    if destination.exists():
        raise FileExistsError(f"Existing sample directory has a different or incomplete snapshot: {destination}")
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        staged = Path(tmp) / alias
        staged.mkdir()
        with urlopen(url, timeout=90) as response, tarfile.open(fileobj=response, mode="r|gz") as archive:
            for member in archive:
                if not member.isfile() or not member.name.endswith(".py"):
                    continue
                _, relative = member.name.split("/", 1)
                target = staged / relative
                if not target.resolve().is_relative_to(staged):
                    raise ValueError("Invalid source path")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
        if source_tree_digest(staged) != entry["tree_sha256"]:
            raise ValueError("Extracted source tree differs from pinned snapshot for " + alias)
        (staged / ".revision").write_text(entry["revision"])
        staged.rename(destination)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("root", type=Path)
    root = cli.parse_args().root.resolve()
    root.mkdir(exist_ok=True, parents=True)
    manifest = json.loads(Path(__file__).with_name("python_corpus.json").read_text())
    for alias, entry in manifest["archives"].items():
        prepare_archive(root, alias, entry)
    github = root / "github"
    github.mkdir(exist_ok=True)
    sources = []
    for repo, entry in manifest["repositories"].items():
        for path, digest in entry["files"].items():
            url = f"https://raw.githubusercontent.com/{repo}/{entry['revision']}/{path}"
            destination = github / (repo + "/" + path).replace("/", "__")
            sources.append((url, destination, digest))
    unexpected = set(github.glob("*.py")) - {destination for _, destination, _ in sources}
    if unexpected:
        raise ValueError(f"Unexpected files in the corpus directory, including {min(unexpected)}")
    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(download_file, sources))
    print(f"{len(sources)} pinned standalone sources plus the Algorithms and Flask source trees at {root}")


if __name__ == "__main__":
    main()
