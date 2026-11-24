"""Normalized constraint atoms used when overload selection changes C++ syntax."""
from itertools import product
from typing import NamedTuple

from .integer_arguments import IntegralArgument


class Constraint(NamedTuple):
    operator: str
    terms: tuple

    def mapped(self, arguments):
        if self.operator == "atom":
            origin, expression = self.terms
            value = expression.substitute(arguments) if expression is not None else None
            return Constraint("atom", (origin, value))
        return Constraint(self.operator, tuple(term.mapped(arguments) for term in self.terms))

    def satisfied(self, arguments):
        if self.operator == "atom":
            value = self.mapped(arguments).terms[1]
            return bool(value.value) if isinstance(value, IntegralArgument) and value.value is not None else None
        values = [term.satisfied(arguments) for term in self.terms]
        if self.operator == "&&":
            return False if False in values else None if None in values else True
        return True if True in values else None if None in values else False

    def clauses(self, split):
        if self.operator == "atom":
            yield frozenset({self})
        elif self.operator == split:
            for term in self.terms:
                yield from term.clauses(split)
        else:
            for group in product(*(term.clauses(split) for term in self.terms)):
                yield frozenset().union(*group)


def more_constrained(left, right):
    if not left or left == right:
        return False
    if not right:
        return True
    first, second = Constraint("&&", left), Constraint("&&", right)

    def subsumes(a, b):
        return all(disjunct & conjunct for disjunct in a.clauses("||") for conjunct in b.clauses("&&"))
    return subsumes(first, second) and not subsumes(second, first)
