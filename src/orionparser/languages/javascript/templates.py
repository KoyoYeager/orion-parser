"""Template literal lexical goals and PLY substitution productions."""
from .strings import read_string


def check_template_size(count, offset, error):
    if count >= 2**32:
        raise error(offset, "too many template elements")


def template_part(grammar, token, initial):
    source = grammar.source
    index = token.lexpos + 1
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
        elif char == "`" or source.startswith("${", index):
            break
        else:
            index += 1
    unfinished = index >= len(source)
    if unfinished:
        grammar.handle_unterminated_template(token, initial, index > len(source))
    spelling = source[token.lexpos + 1:index]
    raw = spelling.replace("\r\n", "\n").replace("\r", "\n")

    def fragment_error(offset, reason):
        return grammar.template_escape_error(token.lexpos + offset, reason)

    try:
        _, cooked = read_string("`" + spelling + "`", 0, True, fragment_error, template=True)
    except ValueError as error:
        token.invalid_escape = error.with_traceback(None)
        cooked = None
    tail = unfinished or source[index] == "`"
    end = len(source) if unfinished else index + (1 if tail else 2)
    if initial:
        token.type = "TEMPLATE" if tail else "TEMPLATE_HEAD"
        if not tail:
            grammar.template_braces.append(0)
    else:
        token.type = "TEMPLATE_TAIL" if tail else "TEMPLATE_MIDDLE"
        if tail:
            grammar.template_braces.pop()
    token.value = source[token.lexpos:end]
    token.quasi = {"type": "TemplateElement", "value": {"raw": raw, "cooked": cooked}, "tail": tail}
    if grammar.preserve_template_spelling and spelling != raw:
        token.quasi["rawText"] = spelling
    grammar.advance_multiline(token, end)
    return token


def propagate_template_escape(production, *children):
    for child in children:
        error = getattr(production.slice[child], "invalid_escape", None)
        if error is not None:
            production.slice[0].invalid_escape = error
            return


class TemplateRules:
    preserve_template_spelling = False

    def handle_unterminated_template(self, token, initial, trailing_escape):
        raise self.error(token.lexpos, "unterminated template")

    def template_escape_error(self, offset, reason):
        return self.error(offset, "invalid escape in untagged template")

    def p_template_plain(self, p):
        """template : TEMPLATE
           untagged_template : TEMPLATE"""
        p.set_lexpos(0, p.lexpos(1))
        propagate_template_escape(p, 1)
        p[0] = {"type": "TemplateLiteral", "quasis": [p.slice[1].quasi], "expressions": []}

    def p_template_span(self, p):
        """template_span : TEMPLATE_HEAD expression
                         | template_span TEMPLATE_MIDDLE expression
           untagged_template_span : UNTAGGED_TEMPLATE_HEAD expression
                                 | untagged_template_span UNTAGGED_TEMPLATE_MIDDLE expression"""
        if len(p) == 3:
            result = {"type": "TemplateLiteral", "quasis": [p.slice[1].quasi], "expressions": [p[2]]}
        else:
            result = p[1]
            result["quasis"].append(p.slice[2].quasi)
            result["expressions"].append(p[3])
        p.set_lexpos(0, p.lexpos(1))
        propagate_template_escape(p, 1, 2)
        p[0] = result

    def p_template_interpolated(self, p):
        """template : template_span TEMPLATE_TAIL
           untagged_template : untagged_template_span UNTAGGED_TEMPLATE_TAIL"""
        p.set_lexpos(0, p.lexpos(1))
        check_template_size(len(p[1]["quasis"]) + 1, p.lexpos(1), self.error)
        p[1]["quasis"].append(p.slice[2].quasi)
        propagate_template_escape(p, 1, 2)
        p[0] = p[1]

    def p_template_primary(self, p):
        "primary : untagged_template"
        if hasattr(p.slice[1], "invalid_escape"):
            raise p.slice[1].invalid_escape
        p[0] = p[1]

    def p_tagged_template(self, p):
        """member : member template
           call : call template"""
        p[0] = {"type": "TaggedTemplateExpression", "tag": p[1], "quasi": p[2]}
