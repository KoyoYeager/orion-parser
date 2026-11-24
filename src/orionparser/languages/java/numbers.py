"""Java literal range checks. Magnitudes are tested before numeric attribution."""


def _float_limits(precision, emin, emax):
    # Ties at half the smallest subnormal round to zero. The midpoint
    # above the largest finite value rounds to infinity.
    denominator_bits = precision - emin
    largest = (1 << (emax + 1)) - (1 << (emax - precision))
    return {
        10: ((str(5 ** denominator_bits), -denominator_bits), (str(largest), 0)),
        2: (("1", -denominator_bits), (format(largest, "b"), 0)),
    }


_LIMITS = {"float": _float_limits(24, -126, 127), "double": _float_limits(53, -1022, 1023)}


def _exponent(text, limit):
    digits = text.lstrip("+-").lstrip("0")
    # Exponents beyond this bound cannot be cancelled by the significand.
    if len(digits) > len(str(limit)):
        return -limit if text.startswith("-") else limit
    magnitude = min(int(digits or "0"), limit)
    return -magnitude if text.startswith("-") else magnitude


def _compare_scaled(digits, exponent, boundary):
    other, shift = boundary
    order = len(digits) + exponent - (len(other) + shift)
    if order:
        return order
    width = max(len(digits), len(other))
    left, right = digits.ljust(width, "0"), other.ljust(width, "0")
    return (left > right) - (left < right)


def _check_float(spelling, hexadecimal):
    kind = "float" if spelling.endswith("f") else "double"
    significand, _, power = spelling.removesuffix("f").removesuffix("d").partition("p" if hexadecimal else "e")
    whole, _, fraction = significand.removeprefix("0x").partition(".")
    digits = (whole + fraction).lstrip("0")
    if not digits:
        return
    exponent = _exponent(power, 4 * len(spelling) + 2048)
    if hexadecimal:
        digits = format(int(digits, 16), "b")
        exponent -= 4 * len(fraction)
    else:
        exponent -= len(fraction)
    low, high = _LIMITS[kind][2 if hexadecimal else 10]
    if _compare_scaled(digits, exponent, high) >= 0:
        raise ValueError("floating-point literal rounds to infinity")
    if _compare_scaled(digits, exponent, low) <= 0:
        raise ValueError("nonzero floating-point literal rounds to zero")


def requires_unary_minus(raw):
    """Validate one lexically complete token; flag the two decimal minima magnitudes."""
    value = raw.lower().replace("_", "")
    hexadecimal = value.startswith("0x")
    if "." in value or ("p" in value if hexadecimal else ("e" in value or value.endswith(("f", "d")))):
        _check_float(value, hexadecimal)
        return False
    bits = 64 if value.endswith("l") else 32
    value = value.removesuffix("l")
    if value.startswith("0"):
        if hexadecimal:
            magnitude, fmt = value[2:], "x"
        elif value.startswith("0b"):
            magnitude, fmt = value[2:], "b"
        else:
            magnitude, fmt = value, "o"
        limit = format((1 << bits) - 1, fmt)
        magnitude = magnitude.lstrip("0") or "0"
        decimal = False
    else:
        magnitude, limit = value, str(1 << (bits - 1))
        decimal = True
    if (len(magnitude), magnitude) > (len(limit), limit):
        raise ValueError("integer literal too large")
    return decimal and magnitude == limit
