"""Symbol extraction from AST.

Walks the AST to collect all defined symbols:
  - functions (def, async def)
  - classes
  - variables (assignments at module/class/function scope)
  - imports
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Symbol:
    """A single extracted symbol."""

    name: str
    kind: str  # "function", "class", "variable", "import"
    scope: str  # e.g. "<module>", "MyClass", "MyClass.method"
    line: int = 0
    docstring: str | None = None


@dataclass
class SymbolTable:
    """All symbols extracted from a module."""

    functions: list[Symbol] = field(default_factory=list)
    classes: list[Symbol] = field(default_factory=list)
    variables: list[Symbol] = field(default_factory=list)
    imports: list[Symbol] = field(default_factory=list)

    @property
    def all(self) -> list[Symbol]:
        return self.functions + self.classes + self.variables + self.imports

    def function_names(self) -> list[str]:
        return [s.name for s in self.functions]

    def class_names(self) -> list[str]:
        return [s.name for s in self.classes]

    def variable_names(self, scope: str | None = None) -> list[str]:
        if scope is not None:
            return [s.name for s in self.variables if s.scope == scope]
        return [s.name for s in self.variables]

    def import_names(self) -> list[str]:
        return [s.name for s in self.imports]

    def to_dict(self) -> dict[str, Any]:
        return {
            "functions": [_sym_dict(s) for s in self.functions],
            "classes": [_sym_dict(s) for s in self.classes],
            "variables": [_sym_dict(s) for s in self.variables],
            "imports": [_sym_dict(s) for s in self.imports],
        }


def _sym_dict(s: Symbol) -> dict[str, Any]:
    d = {"name": s.name, "kind": s.kind, "scope": s.scope, "line": s.line}
    if s.docstring is not None:
        d["docstring"] = s.docstring
    return d


def extract_symbols(ast: dict[str, Any]) -> SymbolTable:
    """Extract all symbol definitions from a Module AST."""
    table = SymbolTable()
    _walk(ast.get("body", []), table, scope="<module>")
    return table


def _walk(
    body: list[Any], table: SymbolTable, scope: str
) -> None:
    """Walk a body list and collect symbols."""
    for node in body:
        if not isinstance(node, dict):
            continue

        node_type = node.get("type", "")
        line = node.get("_line", 0)

        if node_type in ("FunctionDef", "AsyncFunctionDef"):
            name = node.get("name", "")
            table.functions = table.functions + [
                Symbol(name=name, kind="function", scope=scope, line=line,
                       docstring=node.get("docstring"))
            ]
            # Recurse into function body
            func_scope = f"{scope}.{name}" if scope != "<module>" else name
            _walk(node.get("body", []), table, scope=func_scope)

        elif node_type == "ClassDef":
            name = node.get("name", "")
            table.classes = table.classes + [
                Symbol(name=name, kind="class", scope=scope, line=line,
                       docstring=node.get("docstring"))
            ]
            _walk(node.get("body", []), table, scope=name)

        elif node_type == "Assign":
            target = node.get("target", {})
            var_name = _extract_target_name(target)
            if var_name:
                table.variables = table.variables + [
                    Symbol(name=var_name, kind="variable", scope=scope, line=line)
                ]

        elif node_type == "AnnAssign":
            target = node.get("target", {})
            var_name = _extract_target_name(target)
            if var_name:
                table.variables = table.variables + [
                    Symbol(name=var_name, kind="variable", scope=scope, line=line)
                ]

        elif node_type == "Import":
            for imp in node.get("names", []):
                alias = imp.get("alias") or imp.get("name", "")
                table.imports = table.imports + [
                    Symbol(name=alias, kind="import", scope=scope, line=line)
                ]

        elif node_type == "ImportFrom":
            for imp in node.get("names", []):
                alias = imp.get("alias") or imp.get("name", "")
                table.imports = table.imports + [
                    Symbol(name=alias, kind="import", scope=scope, line=line)
                ]

        # Recurse into compound statements
        elif node_type in ("If", "While", "For", "With", "Try"):
            _walk(node.get("body", []), table, scope=scope)
            _walk(node.get("orelse", []), table, scope=scope)
            if node_type == "Try":
                _walk(node.get("finalbody", []), table, scope=scope)
                for handler in node.get("handlers", []):
                    if isinstance(handler, dict):
                        _walk(handler.get("body", []), table, scope=scope)


def _extract_target_name(target: Any) -> str | None:
    """Extract variable name from assignment target."""
    if isinstance(target, dict):
        if target.get("type") == "Name":
            return target.get("id")
        if target.get("type") == "Attribute":
            obj = _extract_target_name(target.get("value"))
            attr = target.get("attr", "")
            if obj:
                return f"{obj}.{attr}"
            return attr
    return None
