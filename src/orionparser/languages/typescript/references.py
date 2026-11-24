"""TypeScript triple-slash reference directives in leading source trivia."""
import re

from orionparser.languages.javascript.pipeline import SourceSyntaxError

_SPACE = r"\t-\r \xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_TRIVIA = re.compile(rf"[{_SPACE}\u0085\u200b]+|\A\#![^\r\n\u2028\u2029]*|/\*[\s\S]*?\*/|//[^\r\n\u2028\u2029]*")
_REFERENCE = re.compile(rf"^///[{_SPACE}]*<(reference|amd-module|amd-dependency)[{_SPACE}].*?/>", re.I | re.ASCII)
_ATTRIBUTES = {
    key: re.compile(rf"""[{_SPACE}]{key}[{_SPACE}]*=[{_SPACE}]*(?:"([^"]*)"|'([^']*)')""", re.I | re.ASCII)
    for key in ("path", "types", "lib", "no-default-lib", "resolution-mode", "preserve", "name")
}
_BREAK = re.compile(r"\r\n|[\n\r\u2028\u2029]")


def references(source):
    directives = []
    module_name = None
    # The compiler reports directive diagnostics by first-seen pragma kind.
    first_errors = {}
    cursor = 0
    while match := _TRIVIA.match(source, cursor):
        cursor = match.end()
        pragma = _REFERENCE.match(match[0])
        if not pragma:
            continue
        tag = pragma[1].lower()
        attrs = {}
        positions = {}
        for key, pattern in _ATTRIBUTES.items():
            attribute = pattern.search(match[0])
            if attribute:
                group = attribute.lastindex
                attrs[key] = attribute[group]
                positions[key] = match.start() + attribute.start(group)
        if tag == "amd-module":
            if "name" in attrs:
                first_errors.setdefault(tag, None)
                if module_name and not first_errors[tag]:
                    first_errors[tag] = (match.start(), len(match[0]), 2458, "duplicate AMD module name")
                module_name = attrs["name"]
                directives.append({"kind": tag, "name": module_name})
            continue
        if tag == "amd-dependency":
            if "path" in attrs:
                dependency = {"kind": tag, "path": attrs["path"]}
                if "name" in attrs:
                    dependency["name"] = attrs["name"]
                directives.append(dependency)
            continue
        kind = next((key for key in ("types", "lib", "path") if key in attrs), None)
        first_errors.setdefault(tag, None)
        error = None
        if attrs.get("no-default-lib") == "true":
            kind = "no-default-lib"
        elif kind is None:
            error = (match.start(), len(match[0]), 1084, "invalid reference directive")
        elif kind == "types" and attrs.get("resolution-mode", "import") not in {"", "require", "import"}:
            error = (positions["types"], len(attrs["types"]), 1453, "resolution-mode must be require or import")
        if error:
            if first_errors[tag] is None:
                first_errors[tag] = error
            continue
        directive = {"kind": kind, "value": attrs[kind]}
        if kind == "types" and attrs.get("resolution-mode"):
            directive["resolutionMode"] = attrs["resolution-mode"]
        if attrs.get("preserve") == "true":
            directive["preserve"] = True
        directives.append(directive)
    for error in first_errors.values():
        if error:
            offset, length, code, message = error
            lines = _BREAK.split(source[:offset])
            raise SourceSyntaxError(offset, f"line {len(lines)}, column {len(lines[-1]) + 1}: {message} (TS{code})",
                                    code=code, length=length)
    return directives
