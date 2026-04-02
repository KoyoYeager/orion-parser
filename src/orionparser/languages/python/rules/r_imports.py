"""Grammar rules for import statements."""


def p_simple_stmt_import(p):
    """simple_stmt : IMPORT dotted_name_list"""
    p[0] = {"type": "Import", "names": p[2], "_line": p.lineno(1)}


def p_simple_stmt_from_import(p):
    """simple_stmt : FROM from_module IMPORT import_names
                   | FROM from_module IMPORT STAR"""
    if len(p) == 5 and p[4] == "*":
        p[0] = {"type": "ImportFrom", "module": p[2], "names": [{"name": "*", "alias": None}], "_line": p.lineno(1)}
    else:
        p[0] = {"type": "ImportFrom", "module": p[2], "names": p[4], "_line": p.lineno(1)}


def p_simple_stmt_from_import_parens(p):
    """simple_stmt : FROM from_module IMPORT LPAREN import_names RPAREN"""
    p[0] = {"type": "ImportFrom", "module": p[2], "names": p[5], "_line": p.lineno(1)}


# --- from_module: absolute or relative ---

def p_from_module_absolute(p):
    """from_module : dotted_name"""
    p[0] = p[1]


def p_from_module_relative(p):
    """from_module : from_dots dotted_name
                   | from_dots"""
    if len(p) == 3:
        p[0] = p[1] + p[2]
    else:
        p[0] = p[1]


def p_from_dots(p):
    """from_dots : DOT
                 | ELLIPSIS
                 | from_dots DOT
                 | from_dots ELLIPSIS"""
    if len(p) == 2:
        p[0] = "." if p[1] == "." else "..."
    else:
        p[0] = p[1] + ("." if p[2] == "." else "...")


def p_dotted_name_list(p):
    """dotted_name_list : dotted_name_list COMMA dotted_name_as
                        | dotted_name_as"""
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    else:
        p[0] = [p[1]]


def p_dotted_name_as(p):
    """dotted_name_as : dotted_name AS NAME
                      | dotted_name"""
    if len(p) == 4:
        p[0] = {"name": p[1], "alias": p[3]}
    else:
        p[0] = {"name": p[1], "alias": None}


def p_import_names(p):
    """import_names : import_names COMMA import_name
                    | import_name"""
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    else:
        p[0] = [p[1]]


def p_import_name(p):
    """import_name : NAME AS NAME
                   | NAME"""
    if len(p) == 4:
        p[0] = {"name": p[1], "alias": p[3]}
    else:
        p[0] = {"name": p[1], "alias": None}


def p_dotted_name(p):
    """dotted_name : dotted_name DOT NAME
                   | NAME"""
    if len(p) == 4:
        p[0] = p[1] + "." + p[3]
    else:
        p[0] = p[1]
