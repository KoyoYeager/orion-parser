"""Grammar rules for simple statements."""


# --- Simple statements ---

def _expr_line(p, idx: int = 1) -> int:
    """Get line number, falling back to expression's _line if non-terminal."""
    line = p.lineno(idx)
    if line == 0 and isinstance(p[idx], dict):
        line = p[idx].get("_line", 0)
    return line


def p_simple_stmt_expr(p):
    """simple_stmt : expression"""
    p[0] = {"type": "Expr", "value": p[1], "_line": _expr_line(p, 1)}


def p_simple_stmt_assign(p):
    """simple_stmt : expression EQUAL expression
                   | expression EQUAL rhs_tuple"""
    p[0] = {"type": "Assign", "target": p[1], "value": p[3], "_line": p.lineno(2) or _expr_line(p, 1)}


def p_simple_stmt_multi_assign(p):
    """simple_stmt : expression EQUAL expression EQUAL expression"""
    # a = b = 1  →  chain assignment
    p[0] = {"type": "Assign", "target": p[1],
            "value": {"type": "Assign", "target": p[3], "value": p[5]},
            "_line": p.lineno(2) or _expr_line(p, 1)}


def p_simple_stmt_tuple_assign(p):
    """simple_stmt : targets EQUAL rhs_tuple
                   | targets EQUAL expression"""
    p[0] = {"type": "Assign",
            "target": p[1],
            "value": p[3], "_line": p.lineno(2)}


def p_targets(p):
    """targets : expression COMMA target_items
              | expression COMMA
              | STAR expression COMMA target_items
              | STAR expression COMMA"""
    if len(p) == 4 and p[1] != "*":
        p[0] = {"type": "Tuple", "elts": [p[1]] + p[3]}
    elif len(p) == 3 and p[1] != "*":
        p[0] = {"type": "Tuple", "elts": [p[1]]}
    elif len(p) == 5:
        p[0] = {"type": "Tuple", "elts": [{"type": "Starred", "value": p[2]}] + p[4]}
    else:
        p[0] = {"type": "Tuple", "elts": [{"type": "Starred", "value": p[2]}]}


def p_target_items(p):
    """target_items : target_items COMMA target_item
                    | target_item"""
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    else:
        p[0] = [p[1]]


def p_target_item(p):
    """target_item : expression
                   | STAR expression"""
    if len(p) == 2:
        p[0] = p[1]
    else:
        p[0] = {"type": "Starred", "value": p[2]}


def p_rhs_tuple(p):
    """rhs_tuple : expression COMMA expression_items
                 | expression COMMA expression_items COMMA
                 | expression COMMA"""
    if len(p) in (4, 5):
        p[0] = {"type": "Tuple", "elts": [p[1]] + p[3]}
    else:
        p[0] = {"type": "Tuple", "elts": [p[1]]}


def p_simple_stmt_aug_assign(p):
    """simple_stmt : expression aug_assign expression"""
    p[0] = {"type": "AugAssign", "target": p[1], "op": p[2], "value": p[3], "_line": _expr_line(p, 1)}


def p_aug_assign(p):
    """aug_assign : PLUSEQUAL
                  | MINEQUAL
                  | STAREQUAL
                  | SLASHEQUAL
                  | DOUBLESLASHEQUAL
                  | PERCENTEQUAL
                  | DOUBLESTAREQUAL
                  | AMPEREQUAL
                  | VBAREQUAL
                  | CIRCUMFLEXEQUAL
                  | LSHIFTEQUAL
                  | RSHIFTEQUAL
                  | ATEQUAL"""
    p[0] = p[1]


def p_simple_stmt_ann_assign(p):
    """simple_stmt : expression COLON expression
                   | expression COLON expression EQUAL expression"""
    if len(p) == 4:
        p[0] = {"type": "AnnAssign", "target": p[1], "annotation": p[3], "value": None, "_line": p.lineno(1)}
    else:
        p[0] = {"type": "AnnAssign", "target": p[1], "annotation": p[3], "value": p[5], "_line": p.lineno(1)}


def p_simple_stmt_return(p):
    """simple_stmt : RETURN expression
                   | RETURN rhs_tuple
                   | RETURN"""
    if len(p) == 3:
        p[0] = {"type": "Return", "value": p[2], "_line": p.lineno(1)}
    else:
        p[0] = {"type": "Return", "value": None, "_line": p.lineno(1)}


def p_simple_stmt_raise(p):
    """simple_stmt : RAISE expression
                   | RAISE expression FROM expression
                   | RAISE"""
    if len(p) == 5:
        p[0] = {"type": "Raise", "exc": p[2], "cause": p[4]}
    elif len(p) == 3:
        p[0] = {"type": "Raise", "exc": p[2]}
    else:
        p[0] = {"type": "Raise", "exc": None}


def p_simple_stmt_pass(p):
    """simple_stmt : PASS"""
    p[0] = {"type": "Pass", "_line": p.lineno(1)}


def p_simple_stmt_break(p):
    """simple_stmt : BREAK"""
    p[0] = {"type": "Break"}


def p_simple_stmt_continue(p):
    """simple_stmt : CONTINUE"""
    p[0] = {"type": "Continue"}


def p_simple_stmt_del(p):
    """simple_stmt : DEL expression"""
    p[0] = {"type": "Delete", "target": p[2]}


def p_simple_stmt_assert(p):
    """simple_stmt : ASSERT expression
                   | ASSERT expression COMMA expression"""
    if len(p) == 3:
        p[0] = {"type": "Assert", "test": p[2], "msg": None}
    else:
        p[0] = {"type": "Assert", "test": p[2], "msg": p[4]}


def p_simple_stmt_global(p):
    """simple_stmt : GLOBAL name_list"""
    p[0] = {"type": "Global", "names": p[2]}


def p_simple_stmt_nonlocal(p):
    """simple_stmt : NONLOCAL name_list"""
    p[0] = {"type": "Nonlocal", "names": p[2]}


def p_name_list(p):
    """name_list : name_list COMMA NAME
                 | NAME"""
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    else:
        p[0] = [p[1]]


def p_simple_stmt_yield(p):
    """simple_stmt : YIELD expression
                   | YIELD"""
    if len(p) == 3:
        p[0] = {"type": "Yield", "value": p[2]}
    else:
        p[0] = {"type": "Yield", "value": None}


def p_simple_stmt_yield_from(p):
    """simple_stmt : YIELD FROM expression"""
    p[0] = {"type": "YieldFrom", "value": p[3]}


# --- type alias (Python 3.12) using soft keyword token ---

def p_simple_stmt_type_alias(p):
    """simple_stmt : TYPE_KW NAME EQUAL expression"""
    p[0] = {"type": "TypeAlias", "name": p[2], "value": p[4], "_line": p.lineno(1)}
