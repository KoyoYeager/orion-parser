"""Grammar rules for module-level structure."""


def p_file_input(p):
    """file_input : statements ENDMARKER
                  | ENDMARKER"""
    if len(p) == 3:
        p[0] = {"type": "Module", "body": p[1]}
    else:
        p[0] = {"type": "Module", "body": []}


def p_statements(p):
    """statements : statements statement
                  | statement"""
    if len(p) == 3:
        p[0] = p[1] + [p[2]] if p[2] else p[1]
    else:
        p[0] = [p[1]] if p[1] else []


def p_statement(p):
    """statement : simple_stmt NEWLINE
                 | compound_stmt"""
    p[0] = p[1]


def p_statement_newline_only(p):
    """statement : NEWLINE"""
    p[0] = None
