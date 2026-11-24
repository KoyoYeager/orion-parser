"""ECMAScript control-flow productions and label resolution within function boundaries."""


class ControlFlowRules:
    check_control_flow_early_errors = True

    def p_while(self, p):
        "statement : WHILE LPAREN expression RPAREN statement"
        p[0] = {"type": "WhileStatement", "test": p[3], "body": p[5]}

    def p_do_while(self, p):
        "statement : DO statement WHILE LPAREN expression RPAREN DO_SEMI"
        p[0] = {"type": "DoWhileStatement", "test": p[5], "body": p[2]}

    def p_labelled(self, p):
        """statement : identifier COLON statement
                     | identifier COLON annex_function"""
        p[0] = {"type": "LabeledStatement", "label": p[1], "body": p[3]}
        self.jump_offsets[id(p[0])] = p.lexpos(1)

    def p_jump(self, p):
        """statement : BREAK_STMT SEMICOLON
                     | BREAK_STMT identifier SEMICOLON
                     | CONTINUE_STMT SEMICOLON
                     | CONTINUE_STMT identifier SEMICOLON"""
        p[0] = {"type": "BreakStatement" if p[1] == "break" else "ContinueStatement",
                "label": p[2] if len(p) == 4 else None}
        self.jump_offsets[id(p[0])] = p.lexpos(1)

    def p_switch(self, p):
        "statement : SWITCH LPAREN expression RPAREN LBRACE clauses RBRACE"
        if self.check_control_flow_early_errors and sum(clause["test"] is None for clause in p[6]) > 1:
            raise self.error(p.lexpos(1), "multiple default clauses")
        p[0] = {"type": "SwitchStatement", "discriminant": p[3], "cases": p[6]}

    def p_clauses(self, p):
        """clauses :
                   | clauses clause"""
        if len(p) == 1:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_clause(self, p):
        """clause : CASE expression COLON body
                  | DEFAULT COLON body"""
        p[0] = {"type": "SwitchCase", "test": p[2] if len(p) == 5 else None,
                "consequent": p[len(p) - 1]}


_ITERATIONS = {"ForStatement", "ForInStatement", "ForOfStatement", "WhileStatement", "DoWhileStatement"}


def validate_jumps(body, offsets, error):
    """Resolve breaks and continues after the complete labelled item is known."""
    pending = [(body, False, False, frozenset(), frozenset())]
    while pending:
        node, can_break, can_continue, labels, loop_labels = pending.pop()
        if isinstance(node, list):
            children = node
        elif isinstance(node, dict):
            kind = node.get("type")
            if kind in _ITERATIONS or kind in {"WithStatement", "IfStatement"}:
                branches = (node["consequent"], node["alternate"]) if kind == "IfStatement" else (node["body"],)
                for branch in branches:
                    if branch and branch["type"] == "LabeledStatement":
                        target = branch
                        while target["type"] == "LabeledStatement":
                            target = target["body"]
                        if target["type"] == "FunctionDeclaration":
                            raise error(offsets[id(branch)], "labelled function in statement position")
            if kind in {"FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression", "StaticBlock"}:
                can_break = can_continue = False
                labels = loop_labels = frozenset()
            elif kind in _ITERATIONS:
                can_break = can_continue = True
            elif kind == "SwitchStatement":
                can_break = True
            elif kind == "LabeledStatement":
                label = node["label"]["name"]
                if label in labels:
                    raise error(offsets[id(node)], "duplicate label " + label)
                labels = labels | {label}
                target = node["body"]
                while target["type"] == "LabeledStatement":
                    target = target["body"]
                if target["type"] in _ITERATIONS:
                    loop_labels = loop_labels | {label}
            elif kind in {"BreakStatement", "ContinueStatement"}:
                is_break = kind == "BreakStatement"
                valid = can_break if is_break else can_continue
                if node["label"]:
                    valid = node["label"]["name"] in (labels if is_break else loop_labels)
                if not valid:
                    raise error(offsets[id(node)], "invalid jump target")
            children = node.values()
        else:
            continue
        pending.extend((child, can_break, can_continue, labels, loop_labels) for child in children
                       if isinstance(child, (dict, list)))
