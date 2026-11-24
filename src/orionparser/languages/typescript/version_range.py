"""Match package export conditions against the syntax reference compiler version."""
import re

# A release sorts after prereleases of the same major/minor/patch.
_COMPILER = (5, 9, 3, True)
_WHITESPACE = re.compile(r"[ \t-\r\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+")
_PART = r"(0|[1-9][0-9]*|[xX*])"
_PARTIAL = re.compile(_PART + r"(?:\." + _PART + r"(?:\." + _PART
                      + r"(?:-([a-z0-9.-]+))?(?:\+[a-z0-9.-]+)?)?)?", re.I | re.ASCII)


def _partial(text):
    match = _PARTIAL.fullmatch(text)
    if not match:
        raise ValueError
    numbers = []
    for part in match.groups()[:3]:
        if part is None or part.lower() in {"*", "x"}:
            break
        numbers.append(int(part))
    precision = len(numbers)
    numbers.extend([0] * (3 - precision))
    return (*numbers, match[4] is None), precision


def _next(version, index):
    numbers = list(version[:3])
    numbers[index] += 1
    numbers[index + 1:] = [0] * (2 - index)
    return (*numbers, True)


def _compare(operator, text):
    lower, precision = _partial(text)
    if not precision:
        return operator not in {"<", ">"}
    if operator in {"^", "~"}:
        index = min(1, precision - 1)
        if operator == "^":
            index = next((i for i in range(precision) if lower[i]), precision - 1)
        return lower <= _COMPILER < _next(lower, index)
    if operator == "<":
        return _COMPILER < lower
    if operator == ">=":
        return _COMPILER >= lower
    if operator == "<=":
        return _COMPILER <= lower if precision == 3 else _COMPILER < _next(lower, precision - 1)
    if operator == ">":
        return _COMPILER > lower if precision == 3 else _COMPILER >= _next(lower, precision - 1)
    return _COMPILER == lower if precision == 3 else lower <= _COMPILER < _next(lower, precision - 1)


def _matches_set(text):
    ends = text.split(" - ")
    if len(ends) == 2:
        left = _compare(">=", ends[0])
        right = _compare("<=", ends[1])
        return left and right
    matched = True
    for term in text.split(" "):
        match = re.fullmatch(r"(>=|<=|[~^<>=]?)([a-zA-Z0-9+.*-]+)", term)
        if not match:
            raise ValueError
        operator, operand = match.groups()
        matched &= _compare(operator, operand)
    return matched


def matches_compiler_version(spec):
    try:
        spec = _WHITESPACE.sub(" ", spec).strip(" ")
        alternatives = [_matches_set(part.strip(" ")) for part in spec.split("||") if part]
    except ValueError:
        return False
    return not alternatives or any(alternatives)
