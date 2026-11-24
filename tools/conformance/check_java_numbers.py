"""Exercise Java numeric literal magnitudes at and on both sides of rounding boundaries."""
import argparse
from pathlib import Path
import tempfile

from check_java_modules import ROOT, reference_results
from orionparser.registry import get_pipeline


def cases():
    for bits, suffix in [(32, ""), (64, "L")]:
        minimum_magnitude = 1 << (bits-1)
        for sign in ("", "-"):
            for delta in (-1, 0, 1):
                yield sign + str(minimum_magnitude+delta) + suffix, delta < 0 or (sign == "-" and delta == 0)
        yield "-(" + str(minimum_magnitude) + suffix + ")", False
        for radix, prefix in [("x", "0x"), ("b", "0b"), ("o", "0")]:
            for delta in (-1, 0):
                yield prefix + format((1 << bits) + delta, radix) + suffix, delta == -1
    for precision, emin, emax, suffix in [(24, -126, 127, "f"), (53, -1022, 1023, "d")]:
        # Midpoint between zero and the smallest subnormal, represented exactly in decimal.
        n = precision - emin
        half_min = 5 ** n
        # Midpoint between the last finite number and the overflow exponent.
        half_max = (1 << (emax+1)) - (1 << (emax-precision))
        for delta in (-1, 0, 1):
            yield f"{half_min+delta}e-{n}{suffix}", delta > 0
            yield f"{half_max+delta}.0{suffix}", delta < 0
        yield f"0x1p-{n}{suffix}", False
        yield f"0x1.00000000000000000001p-{n}{suffix}", True
        yield f"0x{half_max-1:x}p0{suffix}", True
        yield f"0x{half_max:x}p0{suffix}", False
        yield "0.000e-" + "9"*100 + suffix, True
        yield "0x0.0p+" + "9"*100 + suffix, True
        yield "1.0e+" + "9"*100 + suffix, False
        yield "0x1p-" + "9"*100 + suffix, False


def run(jdk):
    with tempfile.TemporaryDirectory() as folder:
        stage = Path(folder)
        inputs = {}
        for i, (literal, accepted) in enumerate(cases()):
            path = stage / f"N{i}.java"
            path.write_text("class N { Object value = " + literal + "; }\n")
            inputs[path] = (literal, accepted)
        for (path, (literal, accepted)), reference in zip(inputs.items(), reference_results(jdk, stage, list(inputs)), strict=True):
            result = get_pipeline(path).analyze_file(path)
            if accepted != reference["accepted"] or accepted != result.success:
                raise ValueError(f"{literal}: expected {accepted}, javac {reference['errors']}, Orion {result.errors}")
            if not accepted:
                diagnostic = reference["errors"][0]
                if not any(e.startswith(f"line {diagnostic['line']}, column {diagnostic['column']}:") for e in result.errors):
                    raise ValueError(f"{literal}: Orion {result.errors}, javac {diagnostic}")
    print(f"{len(inputs)} numeric boundary cases matched javac acceptance and rejection locations")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--jdk", type=Path, default=ROOT / ".venv/toolchains/jdk-21.0.2")
    run(cli.parse_args().jdk)
