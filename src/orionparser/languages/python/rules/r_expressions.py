"""Grammar rules for expressions."""


# --- Primary expressions ---

def p_expression_name(p):
    """expression : NAME"""
    p[0] = {"type": "Name", "id": p[1], "_line": p.lineno(1)}


def p_expression_number(p):
    """expression : NUMBER"""
    p[0] = {"type": "Num", "value": p[1], "_line": p.lineno(1)}


def p_expression_string(p):
    """expression : STRING"""
    p[0] = {"type": "Str", "value": p[1], "_line": p.lineno(1)}


def p_expression_true(p):
    """expression : TRUE"""
    p[0] = {"type": "Constant", "value": True}


def p_expression_false(p):
    """expression : FALSE"""
    p[0] = {"type": "Constant", "value": False}


def p_expression_none(p):
    """expression : NONE"""
    p[0] = {"type": "Constant", "value": None}


def p_expression_ellipsis(p):
    """expression : ELLIPSIS"""
    p[0] = {"type": "Constant", "value": "..."}


# --- Parenthesized / Tuple / Generator ---

def p_expression_paren(p):
    """expression : LPAREN expression RPAREN"""
    p[0] = p[2]


def p_expression_tuple(p):
    """expression : LPAREN expression COMMA RPAREN"""
    p[0] = {"type": "Tuple", "elts": [p[2]]}


def p_expression_tuple_multi(p):
    """expression : LPAREN expression COMMA expression_items RPAREN
                  | LPAREN expression COMMA expression_items COMMA RPAREN
                  | LPAREN STAR expression COMMA expression_items RPAREN
                  | LPAREN STAR expression COMMA expression_items COMMA RPAREN"""
    if p[2] == "*" or (isinstance(p[2], str) and p[2] == "*"):
        first = {"type": "Starred", "value": p[3]}
        p[0] = {"type": "Tuple", "elts": [first] + p[5]}
    else:
        p[0] = {"type": "Tuple", "elts": [p[2]] + p[4]}


def p_expression_empty_tuple(p):
    """expression : LPAREN RPAREN"""
    p[0] = {"type": "Tuple", "elts": []}


def p_expression_generator(p):
    """expression : LPAREN expression comp_for RPAREN"""
    p[0] = {"type": "GeneratorExp", "elt": p[2], "generators": p[3]}


# --- expression_items: comma-separated inside containers (NOT a top-level expression) ---

def p_expression_items(p):
    """expression_items : expression_items COMMA expression
                        | expression_items COMMA STAR expression
                        | expression
                        | STAR expression"""
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    elif len(p) == 5:
        p[0] = p[1] + [{"type": "Starred", "value": p[4]}]
    elif len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = [{"type": "Starred", "value": p[2]}]


# --- List / List comprehension ---

def p_expression_list_empty(p):
    """expression : LSQB RSQB"""
    p[0] = {"type": "List", "elts": []}


def p_expression_list_single(p):
    """expression : LSQB expression RSQB
                  | LSQB STAR expression RSQB"""
    if len(p) == 4:
        p[0] = {"type": "List", "elts": [p[2]]}
    else:
        p[0] = {"type": "List", "elts": [{"type": "Starred", "value": p[3]}]}


def p_expression_list_multi(p):
    """expression : LSQB expression COMMA expression_items RSQB
                  | LSQB expression COMMA expression_items COMMA RSQB
                  | LSQB expression COMMA RSQB
                  | LSQB STAR expression COMMA expression_items RSQB
                  | LSQB STAR expression COMMA expression_items COMMA RSQB
                  | LSQB STAR expression COMMA RSQB"""
    if p[2] == "*":
        first = {"type": "Starred", "value": p[3]}
        if len(p) in (7, 8):
            p[0] = {"type": "List", "elts": [first] + p[5]}
        else:
            p[0] = {"type": "List", "elts": [first]}
    elif len(p) in (6, 7):
        p[0] = {"type": "List", "elts": [p[2]] + p[4]}
    else:
        p[0] = {"type": "List", "elts": [p[2]]}


def p_expression_listcomp(p):
    """expression : LSQB expression comp_for RSQB"""
    p[0] = {"type": "ListComp", "elt": p[2], "generators": p[3]}


# --- Dict / Dict comprehension ---

def p_expression_dict_empty(p):
    """expression : LBRACE RBRACE"""
    p[0] = {"type": "Dict", "keys": [], "values": []}


def p_expression_dict(p):
    """expression : LBRACE kv_pairs RBRACE
                  | LBRACE kv_pairs COMMA RBRACE"""
    keys = [kv[0] for kv in p[2]]
    values = [kv[1] for kv in p[2]]
    p[0] = {"type": "Dict", "keys": keys, "values": values}


def p_expression_dictcomp(p):
    """expression : LBRACE expression COLON expression comp_for RBRACE"""
    p[0] = {"type": "DictComp", "key": p[2], "value": p[4], "generators": p[5]}


def p_kv_pairs(p):
    """kv_pairs : kv_pairs COMMA kv_pair
               | kv_pair"""
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    else:
        p[0] = [p[1]]


def p_kv_pair(p):
    """kv_pair : expression COLON expression"""
    p[0] = (p[1], p[3])


def p_kv_pair_unpack(p):
    """kv_pair : DOUBLESTAR expression"""
    p[0] = (None, p[2])


# --- Set / Set comprehension ---

def p_expression_set_multi(p):
    """expression : LBRACE expression COMMA expression_items RBRACE
                  | LBRACE expression COMMA expression_items COMMA RBRACE
                  | LBRACE expression COMMA RBRACE"""
    if len(p) in (6, 7):
        p[0] = {"type": "Set", "elts": [p[2]] + p[4]}
    else:
        p[0] = {"type": "Set", "elts": [p[2]]}


def p_expression_set_single(p):
    """expression : LBRACE expression RBRACE"""
    p[0] = {"type": "Set", "elts": [p[2]]}


def p_expression_setcomp(p):
    """expression : LBRACE expression comp_for RBRACE"""
    p[0] = {"type": "SetComp", "elt": p[2], "generators": p[3]}


# --- Comprehension clauses ---

def p_comp_for(p):
    """comp_for : COMP_FOR comp_targets COMP_IN expression
               | COMP_FOR comp_targets COMP_IN expression comp_iter"""
    clause = {"target": p[2], "iter": p[4], "ifs": []}
    if len(p) == 6:
        rest = p[5]
        if isinstance(rest, list) and rest and isinstance(rest[0], dict) and "target" in rest[0]:
            p[0] = [clause] + rest
        else:
            clause["ifs"] = rest if isinstance(rest, list) else [rest]
            p[0] = [clause]
    else:
        p[0] = [clause]


def p_comp_targets(p):
    """comp_targets : comp_targets COMMA expression
                    | expression"""
    if len(p) == 4:
        if isinstance(p[1], dict) and p[1].get("type") == "Tuple":
            p[0] = {"type": "Tuple", "elts": p[1]["elts"] + [p[3]]}
        else:
            p[0] = {"type": "Tuple", "elts": [p[1], p[3]]}
    else:
        p[0] = p[1]


def p_comp_iter(p):
    """comp_iter : comp_for
                 | comp_if"""
    p[0] = p[1]


def p_comp_if(p):
    """comp_if : COMP_IF expression
              | COMP_IF expression comp_iter"""
    if len(p) == 3:
        p[0] = [p[2]]
    else:
        rest = p[3]
        if isinstance(rest, list) and rest and isinstance(rest[0], dict) and "target" in rest[0]:
            p[0] = [p[2]]  # ifs for this clause, comp_for handled by parent
        else:
            p[0] = [p[2]] + (rest if isinstance(rest, list) else [rest])


# --- Binary operators ---

def p_expression_binop(p):
    """expression : expression PLUS expression
                  | expression MINUS expression
                  | expression STAR expression
                  | expression SLASH expression
                  | expression DOUBLESLASH expression
                  | expression PERCENT expression
                  | expression DOUBLESTAR expression
                  | expression AT expression
                  | expression AMPER expression
                  | expression VBAR expression
                  | expression CIRCUMFLEX expression
                  | expression LSHIFT expression
                  | expression RSHIFT expression"""
    p[0] = {"type": "BinOp", "left": p[1], "op": p[2], "right": p[3]}


# --- Comparison ---

def p_expression_compare(p):
    """expression : expression LESS expression
                  | expression GREATER expression
                  | expression LESSEQUAL expression
                  | expression GREATEREQUAL expression
                  | expression EQEQUAL expression
                  | expression NOTEQUAL expression"""
    p[0] = {"type": "Compare", "left": p[1], "op": p[2], "right": p[3]}


def p_expression_in(p):
    """expression : expression IN expression
                  | expression NOT IN expression"""
    if len(p) == 4:
        p[0] = {"type": "Compare", "left": p[1], "op": "in", "right": p[3]}
    else:
        p[0] = {"type": "Compare", "left": p[1], "op": "not in", "right": p[4]}


def p_expression_is(p):
    """expression : expression IS expression
                  | expression IS NOT expression"""
    if len(p) == 4:
        p[0] = {"type": "Compare", "left": p[1], "op": "is", "right": p[3]}
    else:
        p[0] = {"type": "Compare", "left": p[1], "op": "is not", "right": p[4]}


# --- Boolean operators ---

def p_expression_boolop(p):
    """expression : expression AND expression
                  | expression OR expression"""
    p[0] = {"type": "BoolOp", "op": p[2], "left": p[1], "right": p[3]}


# --- Unary operators ---

def p_expression_unary(p):
    """expression : MINUS expression %prec UMINUS
                  | PLUS expression %prec UPLUS
                  | TILDE expression %prec UTILDE
                  | NOT expression"""
    p[0] = {"type": "UnaryOp", "op": p[1], "operand": p[2]}


# --- Attribute access ---

def p_expression_attr(p):
    """expression : expression DOT NAME"""
    p[0] = {"type": "Attribute", "value": p[1], "attr": p[3]}


# --- Subscript ---

def p_expression_subscript(p):
    """expression : expression LSQB expression RSQB
                  | expression LSQB expression COMMA expression_items RSQB
                  | expression LSQB expression COMMA expression_items COMMA RSQB
                  | expression LSQB expression COMMA RSQB
                  | expression LSQB subscript_items RSQB"""
    if len(p) == 5:
        p[0] = {"type": "Subscript", "value": p[1], "slice": p[3]}
    elif len(p) in (7, 8) and isinstance(p[5], list):
        p[0] = {"type": "Subscript", "value": p[1],
                "slice": {"type": "Tuple", "elts": [p[3]] + p[5]}}
    elif len(p) == 6:
        p[0] = {"type": "Subscript", "value": p[1],
                "slice": {"type": "Tuple", "elts": [p[3]]}}
    else:
        p[0] = {"type": "Subscript", "value": p[1], "slice": p[3]}


def p_subscript_items(p):
    """subscript_items : subscript_items COMMA subscript_item
                       | subscript_item COMMA subscript_item"""
    if isinstance(p[1], dict) and p[1].get("type") == "Tuple":
        p[0] = {"type": "Tuple", "elts": p[1]["elts"] + [p[3]]}
    elif isinstance(p[1], list):
        p[0] = {"type": "Tuple", "elts": p[1] + [p[3]]}
    else:
        p[0] = {"type": "Tuple", "elts": [p[1], p[3]]}


def p_subscript_item(p):
    """subscript_item : expression
                      | expression COLON expression
                      | COLON expression
                      | expression COLON
                      | COLON
                      | expression COLON expression COLON expression
                      | COLON COLON expression
                      | expression COLON COLON expression
                      | expression COLON COLON
                      | COLON COLON"""
    if len(p) == 2:
        if p[1] == ":":
            p[0] = {"type": "Slice", "lower": None, "upper": None}
        else:
            p[0] = p[1]
    elif len(p) == 3:
        if p[1] == ":":
            p[0] = {"type": "Slice", "lower": None, "upper": p[2]}
        elif p[2] == ":":
            p[0] = {"type": "Slice", "lower": p[1], "upper": None}
        else:
            p[0] = {"type": "Slice", "lower": None, "upper": None, "step": p[2] if p[2] != ":" else None}
    elif len(p) == 4:
        p[0] = {"type": "Slice", "lower": p[1] if p[1] != ":" else None,
                "upper": p[3] if p[3] != ":" else None}
    else:
        # Extended slice with step
        parts = [x for x in list(p)[1:] if x != ":"]
        lower = parts[0] if len(parts) > 0 else None
        upper = parts[1] if len(parts) > 1 else None
        step = parts[2] if len(parts) > 2 else None
        p[0] = {"type": "Slice", "lower": lower, "upper": upper, "step": step}


def p_expression_slice(p):
    """expression : expression LSQB expression COLON expression RSQB
                  | expression LSQB COLON expression RSQB
                  | expression LSQB expression COLON RSQB
                  | expression LSQB COLON RSQB
                  | expression LSQB expression COLON expression COLON expression RSQB
                  | expression LSQB expression COLON expression COLON RSQB
                  | expression LSQB expression COLON COLON expression RSQB
                  | expression LSQB COLON expression COLON expression RSQB
                  | expression LSQB COLON COLON expression RSQB
                  | expression LSQB expression COLON COLON RSQB
                  | expression LSQB COLON COLON RSQB"""
    # Build Slice from the tokens between LSQB and RSQB
    inner = list(p)[3:-1]  # everything between [ and ]
    lower = upper = step = None
    colon_count = inner.count(":")
    if colon_count == 1:
        ci = inner.index(":")
        lower = inner[ci - 1] if ci > 0 and inner[ci - 1] != ":" else None
        upper = inner[ci + 1] if ci + 1 < len(inner) and inner[ci + 1] != ":" else None
    elif colon_count >= 2:
        parts = []
        current = []
        for item in inner:
            if item == ":":
                parts = parts + [current]
                current = []
            else:
                current = current + [item]
        parts = parts + [current]
        lower = parts[0][0] if parts[0] else None
        upper = parts[1][0] if len(parts) > 1 and parts[1] else None
        step = parts[2][0] if len(parts) > 2 and parts[2] else None
    p[0] = {"type": "Subscript", "value": p[1],
            "slice": {"type": "Slice", "lower": lower, "upper": upper, "step": step}}


# --- Function call ---

def p_expression_call(p):
    """expression : expression LPAREN RPAREN
                  | expression LPAREN call_args RPAREN
                  | expression LPAREN call_args COMMA RPAREN"""
    if len(p) == 4:
        p[0] = {"type": "Call", "func": p[1], "args": []}
    else:
        p[0] = {"type": "Call", "func": p[1], "args": p[3]}


def p_call_args(p):
    """call_args : call_args COMMA call_arg
                 | call_arg"""
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    else:
        p[0] = [p[1]]


def p_call_arg(p):
    """call_arg : expression
               | NAME EQUAL expression
               | STAR expression
               | DOUBLESTAR expression
               | expression comp_for
               | STAR NAME"""
    if len(p) == 2:
        p[0] = p[1]
    elif len(p) == 4:
        p[0] = {"type": "keyword", "arg": p[1], "value": p[3]}
    elif len(p) == 3 and p[1] == "*":
        p[0] = {"type": "Starred", "value": p[2]}
    elif len(p) == 3 and p[1] == "**":
        p[0] = {"type": "DictUnpack", "value": p[2]}
    else:
        p[0] = {"type": "GeneratorExp", "elt": p[1], "generators": p[2]}


# --- Starred (only in assignment targets, not general expressions) ---
# Starred in function calls is handled by call_arg rules.


# --- Lambda ---

def p_expression_lambda(p):
    """expression : LAMBDA param_list COLON expression
                  | LAMBDA COLON expression
                  | LAMBDA param_list LAMBDA_COLON expression
                  | LAMBDA LAMBDA_COLON expression"""
    if len(p) == 5:
        p[0] = {"type": "Lambda", "params": p[2], "body": p[4]}
    else:
        p[0] = {"type": "Lambda", "params": [], "body": p[3]}


# --- Ternary ---

def p_expression_ternary(p):
    """expression : expression IF expression ELSE expression"""
    p[0] = {"type": "IfExp", "body": p[1], "test": p[3], "orelse": p[5]}


# --- Walrus ---

def p_expression_walrus(p):
    """expression : NAME COLONEQUAL expression"""
    p[0] = {"type": "NamedExpr", "target": {"type": "Name", "id": p[1]}, "value": p[3]}


# --- Await ---

def p_expression_await(p):
    """expression : AWAIT expression"""
    p[0] = {"type": "Await", "value": p[2]}
