"""Integral class-template arguments and their dependent expressions on the LP64 reference target."""
import operator
from typing import NamedTuple


class IntegralArgument(NamedTuple):
    words: tuple[str, ...]
    value: int | None
    parameter: int | None = None

    def substitute(self, arguments):
        if self.parameter is None:
            return self
        return convert(arguments[self.parameter], self.words)


class IntegralOperation(NamedTuple):
    op: str
    left: "IntegralExpression"
    right: "IntegralExpression | None" = None

    def substitute(self, arguments):
        left = self.left.substitute(arguments)
        right = self.right.substitute(arguments) if self.right is not None else None
        if left is None or self.right is not None and right is None:
            return None
        return evaluate(self.op, left, right)


class DependentIntegralArgument(NamedTuple):
    type_parameter: int
    expression: "IntegralExpression"

    def substitute(self, arguments):
        target = arguments[self.type_parameter]
        value = self.expression.substitute(arguments)
        if value is None or target.layers or target.record:
            return None
        if target.parameter is not None:
            return DependentIntegralArgument(target.parameter, value)
        return convert(value, target.words) if integral_type(target.words) else None


class IntegralConversion(NamedTuple):
    expression: "IntegralExpression"
    words: tuple[str, ...]

    def substitute(self, arguments):
        return convert(self.expression.substitute(arguments), self.words)


IntegralExpression = IntegralArgument | IntegralOperation | IntegralConversion | DependentIntegralArgument


def integral_type(words):
    single = (("auto",), ("bool",), ("wchar_t",), ("char8_t",), ("char16_t",), ("char32_t",))
    return words in single or "int" in words or "char" in words


def convert(argument, words):
    if argument is None:
        return None
    if words == ("auto",):
        return None if isinstance(argument, IntegralArgument) and not argument.words else argument
    if not isinstance(argument, IntegralArgument):
        return IntegralConversion(argument, words)
    return argument._replace(words=words)


def literal_words(spelling, value):
    spelling = spelling.lower().replace("'", "")
    if spelling in ("true", "false"):
        return ("bool",)
    digits = spelling.rstrip("lu")
    suffix = spelling[len(digits):]
    decimal = not digits.startswith("0")
    for rank in range(suffix.count("l"), 3):
        bits = 32 if rank == 0 else 64
        signed = ("int",) + ("long",) * rank
        if "u" not in suffix and value < 1 << (bits - 1):
            return signed
        if ("u" in suffix or not decimal) and value < 1 << bits:
            return (*signed, "unsigned")
    return None


_BINARY = {"+": operator.add, "-": operator.sub, "*": operator.mul, "&": operator.and_,
           "|": operator.or_, "^": operator.xor, "==": operator.eq, "!=": operator.ne,
           "<": operator.lt, ">": operator.gt, "<=": operator.le, ">=": operator.ge}
_UNARY = {"+": operator.pos, "-": operator.neg, "~": operator.invert, "!": operator.not_}
_BINARY_OPERATORS = _BINARY.keys() | {"/", "%", "<<", ">>", "&&", "||"}


def promoted(words):
    if "long" in words or words in (("int",), ("int", "unsigned")):
        return words
    return ("int", "unsigned") if words == ("char32_t",) else ("int",)


def evaluate(op, left, right=None):
    if op not in (_UNARY if right is None else _BINARY_OPERATORS):
        return None
    if not isinstance(left, IntegralArgument) or left.parameter is not None or (
            right is not None and (not isinstance(right, IntegralArgument) or right.parameter is not None)):
        return IntegralOperation(op, left, right)
    if not left.words or right is not None and not right.words:
        return None
    lhs = left.value
    words = promoted(left.words)
    if right is not None:
        rhs = right.value
        if op not in ("<<", ">>"):
            other = promoted(right.words)
            rank = max(words.count("long"), other.count("long"))
            bits = 64 if rank else 32
            # A signed long represents every unsigned int on the reference target;
            # signed long long and unsigned long have the same width.
            unsigned = any("unsigned" in w and (64 if "long" in w else 32) == bits for w in (words, other))
            words = ("int",) + ("long",) * rank + (("unsigned",) if unsigned else ())
            if unsigned:
                lhs %= 1 << bits
                rhs %= 1 << bits
    bits = 64 if "long" in words else 32
    if right is None:
        value = _UNARY[op](lhs)
    elif op in _BINARY:
        value = _BINARY[op](lhs, rhs)
    elif op in ("&&", "||"):
        value = bool(lhs and rhs) if op == "&&" else bool(lhs or rhs)
    elif op in ("<<", ">>"):
        if not 0 <= rhs < bits:
            return None
        value = lhs >> rhs if op == ">>" else (lhs << rhs) % (1 << bits)
        if op == "<<" and "unsigned" not in words and value >= 1 << (bits - 1):
            value -= 1 << bits
    else:
        if rhs == 0 or (lhs == -(1 << (bits - 1)) and rhs == -1):
            return None
        quotient = abs(lhs) // abs(rhs)
        if (lhs < 0) != (rhs < 0):
            quotient = -quotient
        value = quotient if op == "/" else lhs - quotient * rhs
    if isinstance(value, bool):
        return IntegralArgument(("bool",), int(value))
    if "unsigned" in words:
        value %= 1 << bits
    elif not -(1 << (bits - 1)) <= value < 1 << (bits - 1):
        return None
    return IntegralArgument(words, value)
