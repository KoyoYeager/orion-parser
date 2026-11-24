"""Read syntax-relevant TypeScript compiler options from JSONC project files."""
import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path

from .config import parse_config
from .version_range import matches_compiler_version

_NODE_MODULES = {"node16", "node18", "node20", "nodenext"}


def _export_target(root, target, capture="", pattern=False, import_lookup=None):
    if isinstance(target, dict):
        targets = (value for key, value in target.items() if key in {"default", "require", "types", "node"}
                   or (key.startswith("types@") and matches_compiler_version(key[6:])))
    elif isinstance(target, list):
        targets = target
    elif isinstance(target, str):
        if capture and not pattern and not target.endswith("/"):
            return None
        name = target.replace("*", capture) if pattern else target + capture
        if target.startswith("./"):
            if {".", "..", "node_modules"}.intersection(target[2:].split("/") + capture.split("/")):
                return None
            candidate = root / name
            if candidate.suffix == ".json" and candidate.is_file():
                return candidate
        elif import_lookup and not target.startswith(("../", "/")):
            return import_lookup(name)
        return None
    else:
        return None
    for value in targets:
        resolved = _export_target(root, value, capture, pattern, import_lookup)
        if resolved is not None:
            return resolved
    return None


def _export_file(root, exports, key):
    if key == ".":
        if isinstance(exports, dict) and any(k.startswith(".") for k in exports):
            exports = exports.get(".")
        return _export_target(root, exports)
    if not isinstance(exports, dict) or not all(k.startswith(".") for k in exports):
        return None
    return _mapped_file(root, exports, key)


def _pattern_priority(key):
    prefix, star, _ = key.partition("*")
    return len(prefix) + len(star), bool(star), len(key)


def _mapped_file(root, exports, key, import_lookup=None):
    if key in exports and "*" not in key and not key.endswith("/"):
        return _export_target(root, exports[key], import_lookup=import_lookup)
    patterns = (key for key in exports if key.count("*") == 1 or key.endswith("/"))
    for entry in sorted(patterns, key=_pattern_priority, reverse=True):
        prefix, star, suffix = entry.partition("*")
        if star and "*" not in suffix and key.startswith(prefix) and key.endswith(suffix):
            end = len(key) - len(suffix)
            if end > len(prefix) or (end == len(prefix) and not suffix):
                return _export_target(root, exports[entry], key[len(prefix):end], True, import_lookup)
        elif entry.endswith("/") and key.startswith(entry):
            return _export_target(root, exports[entry], key[len(entry):], import_lookup=import_lookup)
    return None


def _package_manifest(directory):
    manifest = directory / "package.json"
    if not manifest.is_file():
        return None
    text = manifest.read_text(encoding="utf-8-sig")
    try:
        value = json.loads(text)
    except ValueError:
        try:
            value = parse_config(text)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _base_file(directory, specifier):
    if not specifier:
        raise ValueError("Empty extends in project configuration")
    specifier = specifier.replace("\\", "/")
    path = Path(specifier)
    if path.is_absolute() or specifier.startswith(("./", "../")):
        candidate = directory / path
        if candidate.is_file():
            return candidate
        if not specifier.endswith(".json"):
            candidate = Path(str(candidate) + ".json")
            if candidate.is_file():
                return candidate
        raise ValueError(f"Cannot resolve inherited configuration {specifier!r} from {directory}")
    resolved = _package_file(directory, specifier, config_lookup=True, active=set())
    if resolved is not None:
        return resolved
    raise ValueError(f"Cannot resolve inherited configuration {specifier!r} from {directory}")


def _version_candidates(manifest, name):
    versions = (manifest or {}).get("typesVersions")
    if not isinstance(versions, dict):
        return None
    # JavaScript enumerates integer index keys before other keys.
    def order(key):
        if key.isascii() and key.isdigit() and len(key) <= 10:
            index = int(key)
            if str(index) == key and index < 2**32 - 1:
                return index
        return 2**32

    paths = next((versions[spec] for spec in sorted(versions, key=order) if matches_compiler_version(spec)), None)
    if not isinstance(paths, dict):
        return None
    capture = ""
    if name in paths and "*" not in name:
        values = paths[name]
    else:
        longest = -1
        values = None
        for pattern, replacements in paths.items():
            prefix, star, suffix = pattern.partition("*")
            if (not star or "*" in suffix or len(prefix) <= longest
                    or len(name) < len(prefix) + len(suffix)
                    or not name.startswith(prefix) or not name.endswith(suffix)):
                continue
            longest = len(prefix)
            values = replacements
            capture = name[len(prefix):len(name) - len(suffix)]
        if longest == -1:
            return None
    if not isinstance(values, list):
        return []
    return [(value, capture) for value in values if isinstance(value, str)]


def _config_candidate(path, config_lookup):
    if path.suffix == ".json" and path.is_file():
        return path
    if config_lookup:
        if path.suffix in {".js", ".ts"}:
            stem = path.name.removesuffix(".d.ts") if path.name.endswith(".d.ts") else path.stem
            replaced = path.with_name(stem + ".json")
            if replaced.is_file():
                return replaced
        candidate = Path(str(path) + ".json")
        if candidate.is_file():
            return candidate
    return None


def _mapped_candidates(directory, substitutions, config_lookup):
    for template, capture in substitutions:
        candidate = directory / (template.replace("*", capture, 1) if capture else template)
        if template.endswith((".ts", ".mts", ".cts", ".js", ".mjs", ".cjs", ".tsx", ".jsx", ".json")) and candidate.is_file():
            return candidate
        resolved = _config_candidate(candidate, config_lookup)
        if resolved is not None:
            return resolved
        if config_lookup and (candidate / "tsconfig.json").is_file():
            return candidate / "tsconfig.json"
    return None


def _package_file(directory, specifier, *, config_lookup, active):
    lookup = directory, specifier
    if lookup in active or not specifier or ":" in specifier:
        return None
    path = Path(specifier)
    parts = path.parts
    package_length = 2 if specifier.startswith("@") else 1
    if not parts:
        return None
    package = Path(*parts[:package_length])
    subpath = "/".join(parts[package_length:])
    export_key = "./" + subpath if subpath else "."
    parents = (directory, *directory.parents)
    for parent in parents:
        scope = _package_manifest(parent)
        if scope is not None:
            imports = scope.get("imports")
            if specifier.startswith("#") and not specifier.startswith("#/") and specifier != "#" and isinstance(imports, dict):
                def resolve_import(target):
                    return _package_file(parent, target, config_lookup=False, active=active | {lookup})

                resolved = _mapped_file(parent, imports, specifier, resolve_import)
                if resolved is not None:
                    return resolved
            if scope.get("name") == package.as_posix():
                resolved = _export_file(parent, scope.get("exports"), export_key)
                if resolved is not None:
                    return resolved
            break
    for parent in parents:
        package_root = parent / "node_modules" / package
        package_manifest = _package_manifest(package_root)
        if package_manifest is not None:
            exports = package_manifest.get("exports")
            if exports is not None and exports is not False and exports != "":
                resolved = _export_file(package_root, exports, export_key)
                if resolved is not None:
                    return resolved
                continue
        root = parent / "node_modules" / path
        manifest = package_manifest if root == package_root else _package_manifest(root)
        if subpath and manifest is None:
            mapped = _version_candidates(package_manifest, subpath)
            if mapped is not None:
                resolved = _mapped_candidates(package_root, mapped, config_lookup)
                if resolved is not None:
                    return resolved
                continue
        resolved = _config_candidate(root, config_lookup)
        if resolved is not None:
            return resolved
        config = (manifest or {}).get("tsconfig") if config_lookup else None
        entry = config if isinstance(config, str) and config else ("tsconfig" if config_lookup else "index")
        entry_path = Path(os.path.normpath(root / entry))
        if entry_path.is_relative_to(root):
            mapped = _version_candidates(manifest, entry_path.relative_to(root).as_posix())
            if mapped is not None:
                resolved = _mapped_candidates(root, mapped, config_lookup)
                if resolved is not None:
                    return resolved
                continue
        resolved = _config_candidate(entry_path, config_lookup)
        if resolved is not None:
            return resolved
        if config_lookup and (entry_path / "tsconfig.json").is_file():
            return entry_path / "tsconfig.json"
        if config_lookup and (root / "tsconfig.json").is_file():
            return root / "tsconfig.json"
    return None


def _compiler_options(path, active):
    path = path.resolve()
    if path in active:
        raise ValueError(f"Cycle in tsconfig extends at {path}")
    text = path.read_text(encoding="utf-8-sig")
    try:
        config = parse_config(text)
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error
    bases = config.get("extends", [])
    if isinstance(bases, str):
        bases = [bases]
    if not isinstance(bases, list) or any(not isinstance(s, str) for s in bases):
        raise ValueError(f"Invalid extends in {path}")
    result = {}
    for base in bases:
        result.update(_compiler_options(_base_file(path.parent, base), active | {path}))
    local = config.get("compilerOptions", {})
    if local is None or isinstance(local, list):
        return result
    if not isinstance(local, dict):
        raise ValueError(f"Invalid compilerOptions in {path}")
    return {**result, **local}


@dataclass(frozen=True)
class SyntaxOptions:
    module_detection: str = "auto"
    module: str = ""
    jsx: str = "preserve"
    always_strict: bool = False
    target: str = "esnext"
    module_resolution: str = ""
    verbatim_module_syntax: bool = False

    @classmethod
    def from_project(cls, filename):
        path = Path(filename)
        options = _compiler_options(path / "tsconfig.json" if path.is_dir() else path, set())
        return cls.from_compiler_options(options)

    @classmethod
    def from_compiler_options(cls, options):
        # A null option clears an inherited value and uses the compiler default.
        options = {name: value for name, value in options.items() if value is not None}
        module = options.get("module", "")
        jsx = options.get("jsx", "preserve")
        if not isinstance(module, str) or not isinstance(jsx, str):
            raise ValueError("module and jsx options must be strings")
        module, jsx = module.lower(), jsx.lower()
        if "module" in options and module not in (_NODE_MODULES | {
            "none", "commonjs", "amd", "system", "umd", "es6", "es2015", "es2020", "es2022", "esnext", "preserve",
        }):
            raise ValueError("Invalid module option")
        if jsx not in {"preserve", "react-native", "react-jsx", "react-jsxdev", "react"}:
            raise ValueError("Invalid jsx option")
        resolution = options.get("moduleResolution", "")
        if "moduleResolution" in options and (not isinstance(resolution, str) or resolution.lower() not in {
            "classic", "node", "node10", "node16", "nodenext", "bundler",
        }):
            raise ValueError("Invalid moduleResolution option")
        target = options.get("target", "es3")
        if not isinstance(target, str) or target.lower() not in {
            "es3", "es5", "es6", "esnext", *(f"es{year}" for year in range(2015, 2025)),
        }:
            raise ValueError("Invalid target option")
        target = target.lower()
        if target == "es3":
            target = {"node16": "es2022", "node18": "es2022", "node20": "es2023",
                      "nodenext": "esnext"}.get(module, "es5")
        default = "force" if module in _NODE_MODULES else "auto"
        detection = options.get("moduleDetection", default)
        if not isinstance(detection, str) or detection.lower() not in {"force", "auto", "legacy"}:
            raise ValueError("Invalid moduleDetection")
        for key in ("alwaysStrict", "strict", "isolatedModules", "verbatimModuleSyntax"):
            if key in options and not isinstance(options[key], bool):
                raise ValueError(f"{key} must be a boolean")
        strict = options.get("alwaysStrict", options.get("strict", False))
        return cls(detection.lower(), module, jsx,
                   strict or options.get("isolatedModules", False) or options.get("verbatimModuleSyntax", False), target,
                   resolution.lower(), options.get("verbatimModuleSyntax", False))

    def effective_module(self):
        if self.module:
            return "es2015" if self.module == "es6" else self.module
        return "commonjs" if self.target in {"es3", "es5"} else "es2015"

    def forces_module(self, path, declaration):
        if declaration or self.module_detection == "legacy":
            return False
        if self.module_detection == "force" or path.suffix in {".mts", ".cts"}:
            return True
        path = Path(os.path.abspath(path))
        node_resolution = self.module_resolution in {"", "node16", "nodenext"}
        if (self.module in _NODE_MODULES and path.suffix in {".ts", ".tsx"}
                and (node_resolution or "node_modules" in path.parts)):
            for parent in path.parents:
                manifest = _package_manifest(parent)
                if manifest is not None:
                    return manifest.get("type") == "module"
        return False


def project_argument(filename):
    try:
        return SyntaxOptions.from_project(filename)
    except (OSError, ValueError) as error:
        raise argparse.ArgumentTypeError(f"{filename}: {error}") from error
