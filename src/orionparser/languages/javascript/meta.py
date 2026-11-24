"""Validate new.target and super in their lexical function and class contexts."""


def validate_meta(body, locations, error):
    # State records availability of new.target, super properties and super().
    root = (False, False, False)
    function = (True, False, False)
    method = (True, True, False)
    pending = [(body, root)]
    while pending:
        node, state = pending.pop()
        if isinstance(node, list):
            pending.extend((child, state) for child in node)
            continue
        if not isinstance(node, dict):
            continue
        role = locations.get(id(node))
        if role and not state[role[0]]:
            raise error(role[1], "invalid " + ("new.target", "super property", "super call")[role[0]])
        kind = node.get("type")
        if kind in {"ClassDeclaration", "ClassExpression"}:
            pending.append((node["superClass"], state))
            for elem in node["body"]["body"]:
                if elem["type"] == "StaticBlock":
                    pending.append((elem["body"], method))
                    continue
                if elem["type"] not in {"MethodDefinition", "PropertyDefinition"}:
                    pending.append((elem, state))
                    continue
                pending.append((elem["key"], state))
                if elem["type"] == "MethodDefinition":
                    derived = elem["kind"] == "constructor" and node["superClass"] is not None
                    method_state = (True, True, derived)
                    pending.extend((elem["value"][key], method_state) for key in ("params", "body"))
                else:
                    pending.append((elem["value"], method))
        elif kind == "Property" and (node["method"] or node["kind"] in {"get", "set"}):
            pending.append((node["key"], state))
            pending.extend((node["value"][key], method) for key in ("params", "body"))
        else:
            if kind in {"FunctionExpression", "FunctionDeclaration"}:
                state = function
            pending.extend((child, state) for child in node.values() if isinstance(child, (dict, list)))
