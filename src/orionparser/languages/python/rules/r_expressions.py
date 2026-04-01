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


# --- Parenthesized / Tuple ---

def p_expression_paren(p):
    """expression : LPAREN expression RPAREN"""
    p[0] = p[2]


def p_expression_tuple(p):
    """expression : LPAREN expression COMMA RPAREN
                  | LPAREN expression COMMA expression_list RPAREN"""
    if len(p) == 5:
        p[0] = {"type": "Tuple", "elts": [p[2]]}
    else:
        p[0] = {"type": "Tuple", "elts": [p[2]] + p[4]}


def p_expression_empty_tuple(p):
    """expression : LPAREN RPAREN"""
    p[0] = {"type": "Tuple", "elts": []}


# --- List / Dict / Set ---

def p_expression_list(p):
    """expression : LSQB RSQB
                  | LSQB expression_list RSQB
                  | LSQB expression_list COMMA RSQB"""
    if len(p) == 3:
        p[0] = {"type": "List", "elts": []}
    else:
        p[0] = {"type": "List", "elts": p[2]}


def p_expression_dict(p):
    """expression : LBRACE RBRACE
                  | LBRACE kv_pairs RBRACE
                  | LBRACE kv_pairs COMMA RBRACE"""
    if len(p) == 3:
        p[0] = {"type": "Dict", "keys": [], "values": []}
    else:
        keys = [kv[0] for kv in p[2]]
        values = [kv[1] for kv in p[2]]
        p[0] = {"type": "Dict", "keys": keys, "values": values}


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


def p_expression_set(p):
    """expression : LBRACE expression_list RBRACE"""
    # Disambiguate from dict: if expression_list is present, it's a set
    p[0] = {"type": "Set", "elts": p[2]}


def p_expression_list_items(p):
    """expression_list : expression_list COMMA expression
                       | expression COMMA expression"""
    if isinstance(p[1], list):
        p[0] = p[1] + [p[3]]
    else:
        p[0] = [p[1], p[3]]


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
    """expression : expression LSQB expression RSQB"""
    p[0] = {"type": "Subscript", "value": p[1], "slice": p[3]}


def p_expression_slice(p):
    """expression : expression LSQB expression COLON expression RSQB
                  | expression LSQB COLON expression RSQB
                  | expression LSQB expression COLON RSQB"""
    if len(p) == 7:
        p[0] = {"type": "Subscript", "value": p[1],
                "slice": {"type": "Slice", "lower": p[3], "upper": p[5]}}
    elif len(p) == 6 and p[3] == ":":
        p[0] = {"type": "Subscript", "value": p[1],
                "slice": {"type": "Slice", "lower": None, "upper": p[4]}}
    else:
        p[0] = {"type": "Subscript", "value": p[1],
                "slice": {"type": "Slice", "lower": p[3], "upper": None}}


# --- Function call ---

def p_expression_call(p):
    """expression : expression LPAREN RPAREN
                  | expression LPAREN arg_list RPAREN"""
    if len(p) == 4:
        p[0] = {"type": "Call", "func": p[1], "args": []}
    else:
        p[0] = {"type": "Call", "func": p[1], "args": p[3]}


# --- Starred ---

def p_expression_starred(p):
    """expression : STAR expression %prec UMINUS"""
    p[0] = {"type": "Starred", "value": p[2]}


# --- Lambda ---

def p_expression_lambda(p):
    """expression : LAMBDA param_list COLON expression
                  | LAMBDA COLON expression"""
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
