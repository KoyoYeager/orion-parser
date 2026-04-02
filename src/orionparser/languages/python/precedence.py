"""Python operator precedence for PLY yacc.

Lowest precedence at top, highest at bottom.
"""

PYTHON_PRECEDENCE = (
    ("left", "OR"),
    ("left", "AND"),
    ("right", "NOT"),
    ("nonassoc", "IN", "IS", "LESS", "GREATER", "LESSEQUAL",
     "GREATEREQUAL", "EQEQUAL", "NOTEQUAL"),
    ("left", "VBAR"),
    ("left", "CIRCUMFLEX"),
    ("left", "AMPER"),
    ("left", "LSHIFT", "RSHIFT"),
    ("left", "PLUS", "MINUS"),
    ("left", "STAR", "SLASH", "DOUBLESLASH", "PERCENT", "AT"),
    ("right", "UPLUS", "UMINUS", "UTILDE"),
    ("right", "DOUBLESTAR"),
    ("left", "DOT", "LPAREN", "LSQB"),
)
