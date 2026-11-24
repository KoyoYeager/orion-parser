"""ECMAScript 2024 linkage declarations and Script/Module entry points."""
from .bindings import bound_names


def export_name(node):
    return node["name"] if node["type"] == "Identifier" else node["value"]


class ModuleRules:
    def p_program(self, p):
        """program : SCRIPT_GOAL body
                   | MODULE_GOAL module_items"""
        p[0] = p[2]

    def p_module_items(self, p):
        """module_items :
                        | module_items list_item
                        | module_items import_decl
                        | module_items export_decl"""
        if len(p) == 1:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_module_name(self, p):
        """module_name : property_name
                       | string_literal"""
        if p[1]["type"] == "Literal":
            try:
                p[1]["value"].encode("utf-16", "surrogatepass").decode("utf-16")
            except UnicodeDecodeError:
                raise self.error(p.lexpos(1), "unpaired surrogate in module export name")
        p.set_lexpos(0, p.lexpos(1))
        p[0] = p[1]

    def p_import_decl(self, p):
        """import_decl : IMPORT string_literal SEMICOLON
                       | IMPORT import_clause FROM string_literal SEMICOLON"""
        p[0] = {"type": "ImportDeclaration", "specifiers": [] if len(p) == 4 else p[2], "source": p[len(p)-2]}

        self.decl_offsets[id(p[0])] = p.lexpos(1)

    def p_import_clause(self, p):
        """import_clause : identifier
                         | other_imports
                         | identifier COMMA other_imports"""
        if p.slice[1].type == "other_imports":
            p[0] = p[1]
        else:
            self.check_import_binding(p[1], p.lexpos(1))
            p[0] = [{"type": "ImportDefaultSpecifier", "local": p[1]}]
            if len(p) == 4:
                p[0].extend(p[3])

    def check_import_binding(self, node, offset):
        name = node.get("name")
        if (name is None or name in self.keywords or name in self.reserved or
                name in {"eval", "arguments", "await", "yield", "let", "static", "implements",
                         "interface", "package", "private", "protected", "public"}):
            raise self.error(offset, "invalid imported binding")

    def p_other_imports(self, p):
        """other_imports : MULTIPLY AS identifier
                         | LBRACE RBRACE
                         | LBRACE import_names RBRACE
                         | LBRACE import_names COMMA RBRACE"""
        if p.slice[1].type == "MULTIPLY":
            self.check_import_binding(p[3], p.lexpos(3))
            p[0] = [{"type": "ImportNamespaceSpecifier", "local": p[3]}]
        else:
            p[0] = [] if len(p) == 3 else p[2]

    def p_module_specifiers(self, p):
        """import_names : import_name
                        | import_names COMMA import_name
           export_names : export_name_spec
                        | export_names COMMA export_name_spec"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_import_name(self, p):
        """import_name : module_name
                       | module_name AS identifier"""
        local = p[1] if len(p) == 2 else p[3]
        self.check_import_binding(local, p.lexpos(1))
        p[0] = {"type": "ImportSpecifier", "local": local, "imported": p[1]}

    def p_export_name_spec(self, p):
        """export_name_spec : module_name
                            | module_name AS module_name"""
        p[0] = {"type": "ExportSpecifier", "local": p[1], "exported": p[1] if len(p) == 2 else p[3]}

    def p_export_names(self, p):
        """named_exports : LBRACE RBRACE
                         | LBRACE export_names RBRACE
                         | LBRACE export_names COMMA RBRACE"""
        p[0] = [] if len(p) == 3 else p[2]

    def p_export_named(self, p):
        """export_decl : EXPORT named_exports SEMICOLON
                       | EXPORT named_exports FROM string_literal SEMICOLON"""
        p[0] = {"type": "ExportNamedDeclaration", "declaration": None, "specifiers": p[2],
                "source": p[4] if len(p) == 6 else None}
        self.export_offsets[id(p[0])] = p.lexpos(1)

    def p_export_all(self, p):
        """export_decl : EXPORT MULTIPLY FROM string_literal SEMICOLON
                       | EXPORT MULTIPLY AS module_name FROM string_literal SEMICOLON"""
        p[0] = {"type": "ExportAllDeclaration", "exported": p[4] if len(p) == 8 else None,
                "source": p[len(p)-2]}
        self.export_offsets[id(p[0])] = p.lexpos(1)

    def p_export_decl(self, p):
        """export_decl : EXPORT variable_declaration SEMICOLON
                       | EXPORT lexical_declaration SEMICOLON
                       | EXPORT function_declaration
                       | EXPORT class_declaration"""
        p[0] = {"type": "ExportNamedDeclaration", "declaration": p[2], "specifiers": [], "source": None}
        self.export_offsets[id(p[0])] = p.lexpos(1)

    def p_default_export(self, p):
        """export_decl : EXPORT DEFAULT assignment SEMICOLON
                       | EXPORT DEFAULT default_declaration"""
        p[0] = {"type": "ExportDefaultDeclaration", "declaration": p[3]}
        self.export_offsets[id(p[0])] = p.lexpos(1)

    def p_default_decl(self, p):
        """default_declaration : DEFAULT_FUNCTION formals function_body
                               | DEFAULT_FUNCTION identifier formals function_body
                               | DEFAULT_FUNCTION MULTIPLY generator_formals generator_body
                               | DEFAULT_FUNCTION MULTIPLY identifier generator_formals generator_body"""
        generator = p.slice[2].type == "MULTIPLY"
        name = next((p[i] for i in range(2, len(p)-2) if p.slice[i].type == "identifier"), None)
        p[0] = self.function_node("FunctionDeclaration", name, p[len(p)-2], p[len(p)-1], p.lexpos(1),
                                  generator=generator)

    def p_default_class(self, p):
        """default_declaration : DEFAULT_CLASS heritage class_body
                               | DEFAULT_CLASS identifier heritage class_body"""
        self.p_class(p)
        p[0]["type"] = "ClassDeclaration"

    def p_import_expression(self, p):
        """call : IMPORT LPAREN assignment RPAREN
           member : IMPORT DOT property_name"""
        if p.slice[2].type == "DOT":
            if self.check_meta_early_errors and (self.source_type != "module" or p[3]["name"] != "meta"
                    or not self.source.startswith("meta", p.lexpos(3))):
                raise self.error(p.lexpos(1), "invalid import.meta")
            p[0] = {"type": "MetaProperty", "meta": {"type": "Identifier", "name": "import"}, "property": p[3]}
        else:
            p[0] = {"type": "ImportExpression", "source": p[3]}


def check_exports(grammar, body):
    declared = set()
    exported = set()
    local_refs = []
    for item in body:
        kind = item["type"]
        decl = item.get("declaration") if kind.startswith("Export") else item
        names = []
        if decl:
            if decl["type"] == "VariableDeclaration":
                names = [name for binding in decl["declarations"] for name in bound_names(binding["id"])]
            elif (decl.get("id") or {}).get("name"):
                names = [decl["id"]["name"]]
            elif kind == "ImportDeclaration":
                names = [spec["local"]["name"] for spec in decl["specifiers"]]
        declared.update(names)
        if kind.startswith("Export"):
            offset = grammar.export_offsets[id(item)]
            if kind == "ExportDefaultDeclaration":
                names = ["default"]
            elif kind == "ExportAllDeclaration":
                names = [export_name(item["exported"])] if item["exported"] else []
            else:
                for spec in item["specifiers"]:
                    names.append(export_name(spec["exported"]))
                    if not item["source"]:
                        local_refs.append((spec["local"], offset))
            for name in names:
                if name in exported:
                    raise grammar.error(offset, "duplicate export " + name)
                exported.add(name)
    # var declarations in nested statements are visible in the module's variable scope.
    pending = list(body)
    while local_refs and pending:
        node = pending.pop()
        if node["type"] == "VariableDeclaration" and node["kind"] == "var":
            for binding in node["declarations"]:
                declared.update(bound_names(binding["id"]))
        elif node["type"] not in {"FunctionDeclaration", "ClassDeclaration"}:
            for field in ("body", "init", "left", "cases", "handler", "block", "finalizer", "consequent", "alternate"):
                child = node.get(field)
                if isinstance(child, list):
                    pending.extend(child)
                elif isinstance(child, dict):
                    pending.append(child)
    for local, offset in local_refs:
        if local.get("name") not in declared:
            raise grammar.error(offset, "unresolved local export " + export_name(local))
