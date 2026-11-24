"""PLY grammar for the object, array and literal values in TypeScript project files."""
from orionparser.languages.javascript.pipeline import Grammar, parser_for_thread


class ConfigLexer(Grammar):
    allow_html_comments = False
    allow_legacy_numeric_literals_and_escapes = False
    t_ignore = Grammar.t_ignore + "\u0085\u200b"


class ConfigGrammar:
    start = "config"
    tokens = ("LBRACE", "RBRACE", "LBRACKET", "RBRACKET", "COLON", "COMMA", "STRING",
              "NUMBER", "MINUS", "TRUE", "FALSE", "NULL")

    def __init__(self, source, goal):
        self.scanner = ConfigLexer(source, goal)
        self.lexer = self.scanner.lexer

    def reset(self, source, goal):
        self.scanner.reset(source, goal)

    def p_config(self, p):
        """config : object
                  | """
        p[0] = p[1] if len(p) == 2 else {}

    def p_object(self, p):
        """object : LBRACE RBRACE
                  | LBRACE properties RBRACE
                  | LBRACE properties COMMA RBRACE"""
        p[0] = {} if len(p) == 3 else p[2]

    def p_properties(self, p):
        """properties : string COLON value
                      | properties COMMA string COLON value"""
        result = {} if len(p) == 4 else p[1]
        result[p[len(p)-3]] = p[len(p)-1]
        p[0] = result

    def p_array(self, p):
        """array : LBRACKET RBRACKET
                 | LBRACKET elements RBRACKET
                 | LBRACKET elements COMMA RBRACKET"""
        p[0] = [] if len(p) == 3 else p[2]

    def p_elements(self, p):
        """elements : value
                    | elements COMMA value"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_value(self, p):
        """value : object
                 | array
                 | string
                 | number"""
        p[0] = p[1]

    def p_literal(self, p):
        """value : TRUE
                 | FALSE
                 | NULL"""
        p[0] = {"true": True, "false": False, "null": None}[p[1]]

    def p_string(self, p):
        "string : STRING"
        if not p[1].startswith('"'):
            raise self.scanner.error(p.lexpos(1), "JSON string requires double quotes", code=1327, length=len(p[1]))
        p[0] = p.slice[1].cooked

    def p_number(self, p):
        """number : NUMBER
                  | MINUS NUMBER"""
        raw = p[len(p)-1].replace("_", "")
        if raw.endswith("n"):
            raise self.scanner.error(p.lexpos(len(p)-1), "BigInt in JSON", code=1328)
        if raw[:2].lower() in {"0x", "0o", "0b"}:
            try:
                value = float(int(raw, 0))
            except OverflowError:
                value = float("inf")
        else:
            value = float(raw)
        p[0] = -value if len(p) == 3 else value

    def p_error(self, token):
        if token is None:
            raise self.scanner.error(len(self.scanner.source), "end of project configuration")
        raise self.scanner.error(token.lexpos, repr(token.value))


def parse_config(source):
    grammar, parser = parser_for_thread(source, "module", ConfigGrammar)
    return parser.parse(lexer=grammar.lexer)
