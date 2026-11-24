"""Recognize implementation-reserved syntax emitted by GNU system headers."""
# Only tokens under a preprocessor line marker with flag 3 enter this adapter.
_ALIASES = {
    "__restrict": ("QUALIFIER", "restrict"), "__restrict__": ("QUALIFIER", "restrict"),
    "__const": ("QUALIFIER", "const"), "__const__": ("QUALIFIER", "const"),
    "__volatile": ("QUALIFIER", "volatile"), "__volatile__": ("QUALIFIER", "volatile"),
    "__inline": ("FUNCTION_SPEC", "inline"), "__inline__": ("FUNCTION_SPEC", "inline"),
    "__auto_type": ("TYPE", "__auto_type"), "__typeof__": ("GNU_TYPEOF", "__typeof__"),
    "_Float128": ("TYPE", "_Float128"),
    "__signed__": ("TYPE", "signed"), "__builtin_va_list": ("TYPE", "__builtin_va_list"),
}
_GROUPED = {"__attribute", "__attribute__", "__asm", "__asm__"}


def header_tokens(tokens, grammar, extensions):
    for token in tokens:
        token.system_header = grammar.in_system_header
        if getattr(token, "gnu_imaginary", False):
            extensions.append({"spelling": token.value, "offset": token.lexpos})
        if not token.system_header or token.type != "NAME":
            yield token
            continue
        spelling = token.value
        if spelling not in _ALIASES and spelling not in _GROUPED and spelling != "__extension__":
            yield token
            continue

        end = token.lexpos + len(spelling)
        if spelling in _GROUPED:
            opening = next(tokens, None)
            if opening is None or opening.type != "(":
                raise grammar.error(token.lexpos, f"expected ( after {spelling}")
            depth = 1
            for item in tokens:
                if item.type == "(":
                    depth += 1
                elif item.type == ")":
                    depth -= 1
                    if not depth:
                        end = item.lexpos + 1
                        break
            else:
                raise grammar.error(token.lexpos, f"unclosed {spelling}")
        extensions.append({"spelling": grammar.source[token.lexpos:end], "offset": token.lexpos})
        if spelling in _ALIASES:
            token.type, token.value = _ALIASES[spelling]
            yield token
