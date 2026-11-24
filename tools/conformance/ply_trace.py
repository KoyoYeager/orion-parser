"""Collect the exact PLY reductions taken by a normal pipeline invocation."""
import sys


def capture_reductions(call, module_prefix, *, exclude=()):
    seen = set()

    def record(frame, event, arg):
        if (event == "call" and frame.f_code.co_name.startswith("p_")
                and frame.f_globals.get("__name__", "").startswith(module_prefix)
                and not isinstance(frame.f_locals.get("self"), exclude)):
            production = frame.f_locals.get("p")
            if production is not None:
                seen.add(production.slice[0].type + " : " + " ".join(s.type for s in production.slice[1:]))

    previous = sys.getprofile()
    sys.setprofile(record)
    try:
        result = call()
    finally:
        sys.setprofile(previous)
    return result, seen
