"""Preprocessing and positioned diagnostics shared by C-family file pipelines."""
import re
import subprocess

from orionparser.core.pipeline import BasePipeline, ParseResult


_NEWLINE = re.compile(r"\r\n|[\r\n]")


# N2176 Annex D and N4861 [lex.name]. The supplementary planes have identical bounds.
_IDENTIFIER_RANGES = (
    (0xA8, 0xA8), (0xAA, 0xAA), (0xAD, 0xAD), (0xAF, 0xAF), (0xB2, 0xB5), (0xB7, 0xBA),
    (0xBC, 0xBE), (0xC0, 0xD6), (0xD8, 0xF6), (0xF8, 0x167F), (0x1681, 0x180D), (0x180F, 0x1FFF),
    (0x200B, 0x200D), (0x202A, 0x202E), (0x203F, 0x2040), (0x2054, 0x2054), (0x2060, 0x206F),
    (0x2070, 0x218F), (0x2460, 0x24FF), (0x2776, 0x2793), (0x2C00, 0x2DFF), (0x2E80, 0x2FFF),
    (0x3004, 0x3007), (0x3021, 0x302F), (0x3031, 0x303F), (0x3040, 0xD7FF),
    (0xF900, 0xFD3D), (0xFD40, 0xFDCF), (0xFDF0, 0xFE44), (0xFE47, 0xFFFD),
)
_NONINITIAL = ((0x300, 0x36F), (0x1DC0, 0x1DFF), (0x20D0, 0x20FF), (0xFE20, 0xFE2F))


def valid_identifier_scalar(cp, *, initial):
    valid = any(lo <= cp <= hi for lo, hi in _IDENTIFIER_RANGES) or (
        0x10000 <= cp <= 0xEFFFD and (cp & 0xFFFF) <= 0xFFFD)
    return valid and not (initial and any(lo <= cp <= hi for lo, hi in _NONINITIAL))


class CParseError(ValueError):
    def __init__(self, source, offset, message):
        self.message = message
        self.offset = offset
        self.line = 1 + sum(1 for _ in _NEWLINE.finditer(source, 0, offset))
        self.column = offset - max(source.rfind(c, 0, offset) for c in "\r\n")
        super().__init__(f"line {self.line}, column {self.column}: {message}")


def source_diagnostic(source, path, error):
    filename, line = str(path), 1
    for text in source.split("\n")[:error.line - 1]:
        marker = re.fullmatch(r'# (\d+) "(?P<file>(?:[^"\\]|\\.)*)"(?: \d+)*', text)
        if marker:
            line, filename = int(marker[1]), marker["file"]
        else:
            line += 1
    return f"{filename}:{line}:{error.column}: {error.message}"


def stack_prefix(parser, kind):
    """Length of the original stack surviving reductions before this token shifts."""
    if kind not in parser.action[parser.statestack[-1]]:
        return None
    states = parser.statestack.copy()
    retained = len(states)
    while True:
        action = parser.action[states[-1]].get(kind)
        if action is None:
            return None
        if action >= 0:
            return retained
        rule = parser.productions[-action]
        if rule.len:
            del states[-rule.len:]
            retained = min(retained, len(states))
        states.append(parser.goto[states[-1]][rule.name])

class CFamilyPipeline(BasePipeline):
    include_dirs = ()
    defines = ()

    def preprocesses_path(self, path):
        return path.suffix in self.source_suffixes or path.suffix.lower() in self.source_suffixes

    def preprocess_file(self, path):
        if not self.preprocesses_path(path):
            # Match the decoding of preprocessor stdout even if a detector
            # guesses Latin-1 from a mostly-ASCII translation unit.
            from orionparser.core.encoding import read_file
            return self.preprocess(read_file(path, prefer_utf8=True))
        command = [self.preprocessor, "-E", "-std=" + self.standard, "-pedantic-errors", "-x", self.dialect]
        command.extend("-I" + str(directory) for directory in self.include_dirs)
        command.extend("-D" + definition for definition in self.defines)
        command.append(str(path.absolute()))
        result = subprocess.run(command, capture_output=True)
        if result.returncode:
            raise ValueError(result.stderr.decode(errors="replace").strip())
        return result.stdout.decode("utf-8")

    def preprocess(self, source):
        return source

    @staticmethod
    def token_record(token):
        return {"type": token.type, "value": getattr(token, "spelling", token.value),
                "line": token.lineno, "offset": token.lexpos}

    def parse(self, source):
        return self._parse(source, None)

    def analyze_file(self, path):
        tokens = []
        try:
            source = self.preprocess_file(path)
            tree = self._parse(source, tokens)
        except CParseError as error:
            message = source_diagnostic(source, path, error) if self.preprocesses_path(path) else str(error)
            return ParseResult(file_path=str(path), success=False, errors=[message], tokens=tokens)
        except (ValueError, OSError) as error:
            return ParseResult(file_path=str(path), success=False, errors=[str(error)], tokens=tokens)
        return ParseResult(file_path=str(path), success=True, ast=tree, tokens=tokens)
