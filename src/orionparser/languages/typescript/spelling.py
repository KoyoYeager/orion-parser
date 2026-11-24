"""Spelling suggestions used in TypeScript 5.9.3 diagnostics."""

# Source order breaks ties between suggestions.
KEYWORDS = """
abstract accessor any asserts assert bigint boolean break case catch class continue const
constructor debugger declare default defer delete else enum export extends false finally for
from function get implements import infer instanceof interface intrinsic keyof let module
namespace never new null number object package private protected public override out readonly
require global return satisfies set static string super switch symbol this throw true try type
typeof undefined unique unknown using var void while with yield async await
""".split()


def spelling_suggestion(name, candidates):
    # The pinned TS scanner compares UTF-16 units. Scores are in tenths:
    # changing case costs 1, an insertion/deletion 10 and a substitution 20.
    def units(value):
        raw = value.encode("utf-16-le", "surrogatepass")
        return [chr(raw[i] | raw[i + 1] << 8) for i in range(0, len(raw), 2)]

    source = units(name)
    best = (len(source) * 2 // 5 + 1) * 10
    suggestion = None
    for candidate in candidates:
        if candidate == name:
            continue
        target = units(candidate)
        if abs(len(target) - len(source)) > max(2, len(source) * 34 // 100):
            continue
        if len(target) < 3 and candidate.lower() != name.lower():
            continue
        band = (best - 1) // 10
        previous = {j: j * 10 for j in range(min(len(target), band) + 1)}
        for i, char in enumerate(source, 1):
            current = {0: i * 10}
            for j in range(max(1, i - band), min(len(target), i + band) + 1):
                other = target[j - 1]
                diagonal = previous.get(j - 1, best)
                if char == other:
                    current[j] = diagonal
                else:
                    cost = 1 if char.lower() == other.lower() else 20
                    current[j] = min(diagonal + cost, previous.get(j, best) + 10, current.get(j - 1, best) + 10)
            previous = current
            if min(current.values()) >= best:
                break
        else:
            score = previous.get(len(target), best)
            if score < best:
                best, suggestion = score, candidate
    return suggestion


def keyword_suggestion(name):
    suggestion = spelling_suggestion(name, KEYWORDS)
    if suggestion:
        return suggestion
    units = len(name.encode("utf-16-le", "surrogatepass")) // 2
    for keyword in KEYWORDS:
        if units > len(keyword) + 2 and name.startswith(keyword):
            return keyword + " " + name[len(keyword):]
    return None
