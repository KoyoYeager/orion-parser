"""Grammar rules for compound statements (if, for, while, def, class, etc.)."""


# --- Compound statements ---

def p_compound_stmt(p):
    """compound_stmt : if_stmt
                     | while_stmt
                     | for_stmt
                     | try_stmt
                     | with_stmt
                     | funcdef
                     | classdef
                     | decorated
                     | match_stmt"""
    p[0] = p[1]


# --- if ---

def p_if_stmt(p):
    """if_stmt : IF expression COLON block elif_chain
              | IF expression COLON block"""
    if len(p) == 6:
        p[0] = {"type": "If", "test": p[2], "body": p[4], "orelse": p[5], "_line": p.lineno(1)}
    else:
        p[0] = {"type": "If", "test": p[2], "body": p[4], "orelse": [], "_line": p.lineno(1)}


def p_elif_chain(p):
    """elif_chain : ELIF expression COLON block elif_chain
                  | ELIF expression COLON block
                  | ELSE COLON block"""
    if len(p) == 4:
        # else clause
        p[0] = p[3]
    elif len(p) == 6:
        p[0] = [{"type": "If", "test": p[2], "body": p[4], "orelse": p[5]}]
    else:
        p[0] = [{"type": "If", "test": p[2], "body": p[4], "orelse": []}]


# --- while ---

def p_while_stmt(p):
    """while_stmt : WHILE expression COLON block
                  | WHILE expression COLON block ELSE COLON block"""
    if len(p) == 5:
        p[0] = {"type": "While", "test": p[2], "body": p[4], "orelse": [], "_line": p.lineno(1)}
    else:
        p[0] = {"type": "While", "test": p[2], "body": p[4], "orelse": p[7], "_line": p.lineno(1)}


# --- for ---

def p_for_stmt(p):
    """for_stmt : FOR for_targets COMP_IN for_iter COLON block
               | FOR for_targets COMP_IN for_iter COLON block ELSE COLON block"""
    if len(p) == 7:
        p[0] = {"type": "For", "target": p[2], "iter": p[4], "body": p[6], "orelse": [], "_line": p.lineno(1)}
    else:
        p[0] = {"type": "For", "target": p[2], "iter": p[4], "body": p[6], "orelse": p[9], "_line": p.lineno(1)}


def p_for_iter(p):
    """for_iter : expression
               | expression COMMA expression_items
               | expression COMMA"""
    if len(p) == 2:
        p[0] = p[1]
    elif len(p) == 4:
        p[0] = {"type": "Tuple", "elts": [p[1]] + p[3]}
    else:
        p[0] = {"type": "Tuple", "elts": [p[1]]}


def p_for_targets(p):
    """for_targets : for_targets COMMA expression
                   | for_targets COMMA STAR expression
                   | expression
                   | STAR expression"""
    if len(p) == 4:
        if isinstance(p[1], dict) and p[1].get("type") == "Tuple":
            p[0] = {"type": "Tuple", "elts": p[1]["elts"] + [p[3]]}
        else:
            p[0] = {"type": "Tuple", "elts": [p[1], p[3]]}
    elif len(p) == 5:
        starred = {"type": "Starred", "value": p[4]}
        if isinstance(p[1], dict) and p[1].get("type") == "Tuple":
            p[0] = {"type": "Tuple", "elts": p[1]["elts"] + [starred]}
        else:
            p[0] = {"type": "Tuple", "elts": [p[1], starred]}
    elif len(p) == 3:
        p[0] = {"type": "Starred", "value": p[2]}
    else:
        p[0] = p[1]


# --- try ---

def p_try_stmt(p):
    """try_stmt : TRY COLON block except_clauses
               | TRY COLON block except_clauses ELSE COLON block
               | TRY COLON block except_clauses FINALLY COLON block
               | TRY COLON block except_clauses ELSE COLON block FINALLY COLON block
               | TRY COLON block FINALLY COLON block"""
    if len(p) == 5:
        p[0] = {"type": "Try", "body": p[3], "handlers": p[4], "orelse": [], "finalbody": []}
    elif len(p) == 8 and p[5] == "else":
        p[0] = {"type": "Try", "body": p[3], "handlers": p[4], "orelse": p[7], "finalbody": []}
    elif len(p) == 8 and p[5] == "finally":
        p[0] = {"type": "Try", "body": p[3], "handlers": p[4], "orelse": [], "finalbody": p[7]}
    elif len(p) == 11:
        # try except else finally
        p[0] = {"type": "Try", "body": p[3], "handlers": p[4], "orelse": p[7], "finalbody": p[10]}
    elif len(p) == 7:
        p[0] = {"type": "Try", "body": p[3], "handlers": [], "orelse": [], "finalbody": p[6]}


def p_except_clauses(p):
    """except_clauses : except_clauses except_clause
                      | except_clause"""
    if len(p) == 3:
        p[0] = p[1] + [p[2]]
    else:
        p[0] = [p[1]]


def p_except_clause(p):
    """except_clause : EXCEPT expression AS NAME COLON block
                     | EXCEPT expression COLON block
                     | EXCEPT expression COMMA NAME COLON block
                     | EXCEPT COLON block
                     | EXCEPT STAR expression AS NAME COLON block
                     | EXCEPT STAR expression COLON block"""
    if len(p) == 7 and p[1] == "except" and p[3] == "as":
        p[0] = {"type": "ExceptHandler", "exc_type": p[2], "name": p[4], "body": p[6]}
    elif len(p) == 7 and p[1] == "except" and p[3] == ",":
        # Python 2 style: except E, v: (treated as except E as v:)
        p[0] = {"type": "ExceptHandler", "exc_type": p[2], "name": p[4], "body": p[6]}
    elif len(p) == 5 and p[1] == "except":
        p[0] = {"type": "ExceptHandler", "exc_type": p[2], "name": None, "body": p[4]}
    elif len(p) == 4:
        p[0] = {"type": "ExceptHandler", "exc_type": None, "name": None, "body": p[3]}
    elif len(p) == 8:
        # except* ExcType as name
        p[0] = {"type": "ExceptHandler", "exc_type": p[3], "name": p[5], "body": p[7], "star": True}
    elif len(p) == 6:
        # except* ExcType
        p[0] = {"type": "ExceptHandler", "exc_type": p[3], "name": None, "body": p[5], "star": True}
    else:
        p[0] = {"type": "ExceptHandler", "exc_type": p[2], "name": None, "body": p[4]}


# --- with ---

def p_with_stmt(p):
    """with_stmt : WITH with_items COLON block"""
    p[0] = {"type": "With", "items": p[2], "body": p[4]}


def p_with_items(p):
    """with_items : with_items COMMA with_item
                  | with_item"""
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    else:
        p[0] = [p[1]]


def p_with_item(p):
    """with_item : expression AS expression
                 | expression WITH_AS expression
                 | expression"""
    if len(p) == 4:
        p[0] = {"context": p[1], "alias": p[3]}
    else:
        p[0] = {"context": p[1], "alias": None}


# --- block (indented suite) ---

def p_block(p):
    """block : NEWLINE INDENT statements DEDENT
             | simple_stmt NEWLINE"""
    if len(p) == 5:
        p[0] = p[3]
    else:
        p[0] = [p[1]]


# --- function definition ---

def p_funcdef(p):
    """funcdef : DEF NAME LPAREN param_list RPAREN COLON block
              | DEF NAME LPAREN RPAREN COLON block
              | DEF NAME LPAREN param_list RPAREN ARROW expression COLON block
              | DEF NAME LPAREN RPAREN ARROW expression COLON block"""
    if len(p) == 8:
        p[0] = {"type": "FunctionDef", "name": p[2], "params": p[4],
                "returns": None, "body": p[7], "_line": p.lineno(1)}
    elif len(p) == 7:
        p[0] = {"type": "FunctionDef", "name": p[2], "params": [],
                "returns": None, "body": p[6], "_line": p.lineno(1)}
    elif len(p) == 10:
        p[0] = {"type": "FunctionDef", "name": p[2], "params": p[4],
                "returns": p[7], "body": p[9], "_line": p.lineno(1)}
    else:  # len(p) == 9
        p[0] = {"type": "FunctionDef", "name": p[2], "params": [],
                "returns": p[6], "body": p[8], "_line": p.lineno(1)}


def p_funcdef_async(p):
    """funcdef : ASYNC DEF NAME LPAREN param_list RPAREN COLON block
              | ASYNC DEF NAME LPAREN RPAREN COLON block
              | ASYNC DEF NAME LPAREN param_list RPAREN ARROW expression COLON block
              | ASYNC DEF NAME LPAREN RPAREN ARROW expression COLON block"""
    if len(p) == 9:
        p[0] = {"type": "AsyncFunctionDef", "name": p[3], "params": p[5],
                "returns": None, "body": p[8]}
    elif len(p) == 8:
        p[0] = {"type": "AsyncFunctionDef", "name": p[3], "params": [],
                "returns": None, "body": p[7]}
    elif len(p) == 11:
        p[0] = {"type": "AsyncFunctionDef", "name": p[3], "params": p[5],
                "returns": p[8], "body": p[10]}
    else:  # len(p) == 10
        p[0] = {"type": "AsyncFunctionDef", "name": p[3], "params": [],
                "returns": p[7], "body": p[9]}


# --- async with / async for ---

def p_async_with(p):
    """compound_stmt : ASYNC with_stmt"""
    p[0] = p[2]
    p[0]["type"] = "AsyncWith"


def p_async_for(p):
    """compound_stmt : ASYNC for_stmt"""
    p[0] = p[2]
    p[0]["type"] = "AsyncFor"


def p_param_list(p):
    """param_list : param_list COMMA param
                  | param_list COMMA
                  | param"""
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    elif len(p) == 3:
        p[0] = p[1]  # trailing comma
    else:
        p[0] = [p[1]]


def p_param(p):
    """param : NAME
             | NAME COLON expression
             | NAME EQUAL expression
             | NAME COLON expression EQUAL expression
             | STAR NAME
             | STAR NAME COLON expression
             | STAR
             | DOUBLESTAR NAME
             | DOUBLESTAR NAME COLON expression"""
    if len(p) == 2:
        if p[1] == "*":
            p[0] = {"name": "*", "annotation": None, "default": None}
        else:
            p[0] = {"name": p[1], "annotation": None, "default": None}
    elif len(p) == 4 and p[2] == ":":
        p[0] = {"name": p[1], "annotation": p[3], "default": None}
    elif len(p) == 4 and p[2] == "=":
        p[0] = {"name": p[1], "annotation": None, "default": p[3]}
    elif len(p) == 6:
        p[0] = {"name": p[1], "annotation": p[3], "default": p[5]}
    elif len(p) == 3 and p[1] == "*":
        p[0] = {"name": "*" + p[2], "annotation": None, "default": None}
    elif len(p) == 3 and p[1] == "**":
        p[0] = {"name": "**" + p[2], "annotation": None, "default": None}
    elif len(p) == 5 and p[1] == "*":
        p[0] = {"name": "*" + p[2], "annotation": p[4], "default": None}
    elif len(p) == 5 and p[1] == "**":
        p[0] = {"name": "**" + p[2], "annotation": p[4], "default": None}


def p_param_star_typed_star(p):
    """param : STAR NAME COLON STAR expression"""
    p[0] = {"name": "*" + p[2], "annotation": {"type": "Starred", "value": p[5]}, "default": None}


# --- class definition ---

def p_classdef(p):
    """classdef : CLASS NAME COLON block
               | CLASS NAME LPAREN RPAREN COLON block
               | CLASS NAME LPAREN call_args RPAREN COLON block
               | CLASS NAME LPAREN call_args COMMA RPAREN COLON block
               | CLASS NAME LSQB expression_items RSQB COLON block
               | CLASS NAME LSQB expression_items RSQB LPAREN call_args RPAREN COLON block
               | CLASS NAME LSQB expression_items RSQB LPAREN RPAREN COLON block"""
    # CLASS NAME COLON block → 5
    # CLASS NAME () COLON block → 7
    # CLASS NAME (args) COLON block → 8
    # CLASS NAME (args,) COLON block → 9
    # CLASS NAME [params] COLON block → 8
    # CLASS NAME [params] () COLON block → 10
    # CLASS NAME [params] (args) COLON block → 11
    if len(p) == 5:
        p[0] = {"type": "ClassDef", "name": p[2], "bases": [], "body": p[4], "_line": p.lineno(1)}
    elif len(p) == 7:
        p[0] = {"type": "ClassDef", "name": p[2], "bases": [], "body": p[6], "_line": p.lineno(1)}
    elif len(p) == 8 and p[3] == "(":
        p[0] = {"type": "ClassDef", "name": p[2], "bases": p[4], "body": p[7], "_line": p.lineno(1)}
    elif len(p) == 8 and p[3] == "[":
        p[0] = {"type": "ClassDef", "name": p[2], "type_params": p[4], "bases": [], "body": p[7], "_line": p.lineno(1)}
    elif len(p) == 9:
        p[0] = {"type": "ClassDef", "name": p[2], "bases": p[4], "body": p[8], "_line": p.lineno(1)}
    elif len(p) == 10:
        p[0] = {"type": "ClassDef", "name": p[2], "type_params": p[4], "bases": [], "body": p[9], "_line": p.lineno(1)}
    else:
        p[0] = {"type": "ClassDef", "name": p[2], "type_params": p[4], "bases": p[8], "body": p[10], "_line": p.lineno(1)}


# --- decorators ---

def p_decorated(p):
    """decorated : decorators funcdef
                 | decorators classdef"""
    p[0] = p[2]
    p[0]["decorators"] = p[1]


def p_decorators(p):
    """decorators : decorators decorator
                  | decorator"""
    if len(p) == 3:
        p[0] = p[1] + [p[2]]
    else:
        p[0] = [p[1]]


def p_decorator(p):
    """decorator : AT expression NEWLINE"""
    p[0] = p[2]


# --- match/case (Python 3.10+) using soft keyword tokens ---

def p_match_stmt(p):
    """match_stmt : MATCH_KW expression COLON NEWLINE INDENT case_clauses DEDENT"""
    p[0] = {"type": "Match", "subject": p[2], "cases": p[6], "_line": p.lineno(1)}


def p_case_clauses(p):
    """case_clauses : case_clauses case_clause
                    | case_clause"""
    if len(p) == 3:
        p[0] = p[1] + [p[2]]
    else:
        p[0] = [p[1]]


def p_case_clause(p):
    """case_clause : CASE_KW expression COLON block
                   | CASE_KW expression COMP_IF expression COLON block"""
    if len(p) == 5:
        p[0] = {"type": "MatchCase", "pattern": p[2], "guard": None, "body": p[4], "_line": p.lineno(1)}
    else:
        p[0] = {"type": "MatchCase", "pattern": p[2], "guard": p[4], "body": p[6], "_line": p.lineno(1)}
