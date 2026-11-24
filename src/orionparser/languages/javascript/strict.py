"""Resolve strict-mode early errors once statement-list directive prologues are known."""

STRICT_IDENTIFIERS = frozenset("implements interface let package private protected public static yield".split())


class StrictRules:
    def strict_statement(self, node, keyword, reason):
        self.strict_violation(keyword.lexpos, reason)

    def strict_violation(self, offset, reason):
        if self.source_type == "module":
            raise self.error(offset, reason)
        self.strict_errors.append((offset, reason))

    def strict_directive(self, statements):
        for stmt in statements:
            expr = stmt.get("expression")
            if stmt["type"] != "ExpressionStatement" or not expr or id(expr) in self.grouped_patterns:
                break
            raw = expr.get("raw", "")
            if expr["type"] != "Literal" or not raw:
                break
            if raw in {'"use strict"', "'use strict'"}:
                return True
        return False

    def check_strict_regions(self, body):
        if not self.strict_errors:
            return
        if self.strict_directive(body):
            self.strict_regions.append((0, len(self.source)))
        for offset, reason in self.strict_errors:
            if any(start <= offset <= end for start, end in self.strict_regions):
                raise self.error(offset, reason)
