"""C++20 translation units parsed with PLY yacc."""
from bisect import bisect_right
from collections import deque
from copy import copy
from itertools import chain
import json
import operator
from threading import Lock, local
from types import SimpleNamespace
from typing import NamedTuple

from ply import yacc

from orionparser.languages.c_family import CFamilyPipeline, CParseError, stack_prefix
from . import integer_arguments
from .integer_arguments import DependentIntegralArgument, IntegralArgument, IntegralExpression
from .attributes import AttributeRules
from .exceptions import ExceptionRules
from .expressions import ExpressionRules
from .classes import ClassRules
from .operators import OperatorRules
from .constraints import ConstraintRules
from .constraint_identity import Constraint, more_constrained
from .lambdas import LambdaRules
from .lexer import BUILTINS, CppSource, TYPE_TRAITS, TYPE_TRANSFORMS, character_argument, floating_literal_type, is_integer_zero_literal, string_array_extent


_FOLD_OPERATORS = frozenset("+ - * / % ^ & | = < > << >> += -= *= /= %= ^= &= |= <<= >>= == != <= >= && || , .* ->*".split())


# Multi-keyword standard types from [dcl.type.simple], independent of word order.
_BUILTIN_COMBINATIONS = {
    tuple(sorted((*sign, *width, *base)))
    for sign in ((), ("signed",), ("unsigned",))
    for width in ((), ("short",), ("long",), ("long", "long"))
    for base in ((), ("int",))
}
_BUILTIN_COMBINATIONS.update({("char", "signed"), ("char", "unsigned"), ("double", "long")})


_UNNAMED_NAMESPACE = "<unnamed namespace>"
_INDIRECT_BINDINGS = {"closure", "object", "member_pointer", "function_type"}
_BINARY_VALUE_OPERATORS = {"+", "-", "*", "/", "%", "<<", ">>", "&", "^", "|",
                           "==", "!=", "<", ">", "<=", ">=", "<=>", "&&", "||"}
_RECEIVER_OPERATORS = {"operator" + op for op in _BINARY_VALUE_OPERATORS | {
    "++", "--", "!", "~", "->*", ",", "=", "*=", "/=", "%=", "+=", "-=", ">>=", "<<=", "&=", "^=", "|="
}}

_BOUND_OPERATIONS = {"+": operator.add, "-": operator.sub, "*": operator.mul,
                     "/": operator.floordiv, "%": operator.mod, "&": operator.and_,
                     "|": operator.or_, "^": operator.xor}

# Fundamental type sizes and natural alignments on x86_64-unknown-linux-gnu.
_FUNDAMENTAL_BYTES = {
    ("bool",): 1, ("char",): 1, ("char", "signed"): 1, ("char", "unsigned"): 1,
    ("char8_t",): 1, ("char16_t",): 2, ("char32_t",): 4, ("wchar_t",): 4,
    ("int", "short"): 2, ("int",): 4, ("int", "long"): 8, ("int", "long", "long"): 8,
    ("float",): 4, ("double",): 8, ("double", "long"): 16,
}


class ReceiverArray(NamedTuple):
    bound: int | None
    omitted: bool = False


class AliasLayer(NamedTuple):
    operator: str
    qualifiers: frozenset[str] = frozenset()
    bound: int | None = None
    member_of: tuple[str, ...] | None = None
    parameters: tuple["AliasIdentity", ...] = ()
    variadic: bool = False
    nonthrowing: bool = False


class TemplateParameter(NamedTuple):
    value_type: "AliasIdentity | None"
    default: "AliasIdentity | IntegralExpression | AddressArgument | FunctionAddressSelection | None"
    pack: bool


class RecordIdentity(NamedTuple):
    scope: tuple[str, ...]
    arguments: tuple["AliasIdentity | IntegralExpression | AddressArgument | FunctionAddressSelection", ...] | None = None


class AliasIdentity(NamedTuple):
    words: tuple[str, ...]
    cv: frozenset[str]
    # Ordered from the base type outward, so a cv qualifier on a pointer alias
    # attaches to its outer pointer.
    layers: tuple[AliasLayer, ...]
    record: RecordIdentity | None = None
    parameter: int | None = None

    def is_dependent(self):
        if self.parameter is not None or any(p.is_dependent() for layer in self.layers for p in layer.parameters):
            return True
        if self.record and self.record.arguments:
            for arg in self.record.arguments:
                if isinstance(arg, AliasIdentity):
                    if arg.is_dependent():
                        return True
                elif not isinstance(arg, (IntegralArgument, AddressArgument)) or arg.parameter is not None:
                    return True
        return False

    def qualified(self, cv):
        if not cv:
            return self
        layers = list(self.layers)
        for index in range(len(layers) - 1, -1, -1):
            layer = layers[index]
            if layer.operator == "[]":
                continue
            if layer.operator in ("*", "::*"):
                layers[index] = layer._replace(qualifiers=layer.qualifiers | cv)
            return self._replace(layers=tuple(layers))
        return self._replace(cv=self.cv | cv)

    def parameter_type(self):
        if not self.layers:
            return self._replace(cv=frozenset())
        outer = self.layers[-1]
        if outer.operator == "[]":
            return self._replace(layers=(*self.layers[:-1], AliasLayer("*")))
        if outer.operator == "()":
            return self._replace(layers=(*self.layers, AliasLayer("*")))
        if outer.operator in ("*", "::*"):
            return self._replace(layers=(*self.layers[:-1], outer._replace(qualifiers=frozenset())))
        return self

    def substitute(self, arguments):
        base = self
        if self.parameter is not None:
            base = arguments[self.parameter].qualified(self.cv)
        elif self.record is not None and self.record.arguments:
            params = tuple(arg.substitute(arguments) for arg in self.record.arguments)
            if None in params:
                return None
            base = self._replace(record=self.record._replace(arguments=params))
        if self.parameter is None and not any(layer.parameters for layer in self.layers):
            return base
        layers = list(base.layers) if self.parameter is not None else []
        for layer in self.layers:
            if layer.parameters:
                params = tuple(arg.substitute(arguments) for arg in layer.parameters)
                if None in params:
                    return None
                layer = layer._replace(parameters=tuple(arg.parameter_type() for arg in params))
            append_alias_layer(layers, layer)
        return base._replace(layers=tuple(layers))


def append_alias_layer(layers, layer):
    if layers and layers[-1].operator in {"&", "&&"} and layer.operator in {"&", "&&"}:
        op = "&" if "&" in (layers.pop().operator, layer.operator) else "&&"
        layer = layer._replace(operator=op)
    layers.append(layer)


class TypeLayout(NamedTuple):
    size: int | None
    alignment: int | None
    layers: tuple[AliasLayer, ...]

    @classmethod
    def from_identity(cls, alias):
        words = tuple(w for w in alias.words if w != "unsigned" or "int" not in alias.words)
        size = _FUNDAMENTAL_BYTES.get(words)
        return cls(size, size, alias.layers)


    def measure(self, op):
        size = self.size if op == "sizeof" else self.alignment
        for index, layer in enumerate(self.layers):
            if layer.operator == "()":
                size = None
            elif layer.operator in ("*", "::*"):
                method = layer.operator == "::*" and index > 0 and self.layers[index-1].operator == "()"
                size = 16 if method and op == "sizeof" else 8
            elif layer.operator == "[]" and op == "sizeof":
                size = size * layer.bound if size is not None and layer.bound is not None else None
        return size


class MeasureArgument(NamedTuple):
    op: str
    identity: AliasIdentity

    def substitute(self, arguments):
        identity = self.identity.substitute(arguments)
        if identity is None:
            return None
        if identity.is_dependent():
            return self._replace(identity=identity)
        value = TypeLayout.from_identity(identity).measure(self.op)
        return IntegralArgument(("int", "long", "unsigned"), value) if value is not None else None


class ReceiverType(NamedTuple):
    receiver: tuple
    identity: AliasIdentity | None


class AddressArgument(NamedTuple):
    declared_type: AliasIdentity
    origin: tuple[str, ...] | None
    indices: tuple[int, ...] = ()
    parameter: int | None = None
    past_object: bool = False
    specialization: tuple = ()

    def displaced(self, distance):
        if distance == 0:
            return self
        if self.origin is None:
            return None
        if self.indices:
            index = self.indices[-1] + distance
            return self._replace(indices=(*self.indices[:-1], index)) if index >= 0 else None
        position = int(self.past_object) + distance
        return self._replace(past_object=bool(position)) if position in (0, 1) else None

    def substitute(self, arguments):
        target = self.declared_type.substitute(arguments)
        if target is None:
            return None
        if self.parameter is None:
            return self._replace(declared_type=target)
        supplied = arguments[self.parameter]
        if not isinstance(supplied, AddressArgument):
            return None
        return supplied if target.words == ("auto",) else supplied._replace(declared_type=target)


def deduce_function_type(pattern, actual, arguments):
    """Match the declarator layers from the outside in, leaving the substituted base type."""
    if len(actual.layers) < len(pattern.layers):
        return False
    remaining = len(actual.layers) - len(pattern.layers)
    for formal, supplied in zip(pattern.layers, actual.layers[remaining:]):
        if formal.operator != supplied.operator or len(formal.parameters) != len(supplied.parameters):
            return False
        if any(not deduce_function_type(f, a, arguments) for f, a in zip(formal.parameters, supplied.parameters)):
            return False
    if pattern.parameter is not None:
        index = pattern.parameter
        base = actual._replace(layers=actual.layers[:remaining])
        if pattern.cv:
            layers = list(base.layers)
            outer = next((i for i in reversed(range(len(layers))) if layers[i].operator != "[]"), None)
            if outer is None:
                base = base._replace(cv=base.cv - pattern.cv)
            elif layers[outer].operator in ("*", "::*"):
                layers[outer] = layers[outer]._replace(qualifiers=layers[outer].qualifiers - pattern.cv)
                base = base._replace(layers=tuple(layers))
        if arguments[index] is None:
            arguments[index] = base
        return arguments[index] == base
    if pattern.record and pattern.record.arguments:
        if not actual.record or pattern.record.scope != actual.record.scope:
            return False
        supplied = actual.record.arguments or ()
        if len(pattern.record.arguments) != len(supplied):
            return False
        for f, a in zip(pattern.record.arguments, supplied):
            if isinstance(f, AliasIdentity) and isinstance(a, AliasIdentity):
                if not deduce_function_type(f, a, arguments):
                    return False
            elif f != a:
                return False
    return True


class ClassPattern(NamedTuple):
    arguments: tuple
    arity: int
    pack: object = None
    pack_parameters: tuple[int, ...] = ()

    def accepts(self, supplied):
        if len(self.arguments) > len(supplied) or (self.pack is None and len(self.arguments) != len(supplied)):
            return False
        deduced = [None] * self.arity

        def deduce(pattern, actual, values):
            if isinstance(pattern, AliasIdentity):
                return isinstance(actual, AliasIdentity) and deduce_function_type(pattern, actual, values)
            if isinstance(pattern, IntegralArgument) and pattern.parameter is not None:
                if not isinstance(actual, IntegralArgument):
                    return False
                i = pattern.parameter
                if values[i] is None:
                    values[i] = actual
                return values[i] == actual
            return True

        if not all(deduce(f, a, deduced) for f, a in zip(self.arguments, supplied)):
            return False
        if any(v is None and i not in self.pack_parameters for i, v in enumerate(deduced)):
            return False
        if any(f.substitute(deduced) != a for f, a in zip(self.arguments, supplied)):
            return False
        for arg in supplied[len(self.arguments):]:
            values = deduced.copy()
            if not deduce(self.pack, arg, values) or self.pack.substitute(values) != arg:
                return False
        return True

    def accepts_pattern(self, other):
        if not self.accepts(other.arguments):
            return False
        return other.pack is None or (self.pack is not None and self.accepts((*other.arguments, other.pack)))


def constraints_satisfied(constraints, arguments):
    return all(c.satisfied(arguments) is True for c in constraints)


class TemplateFunction(NamedTuple):
    address: AddressArgument
    defaults: tuple[AliasIdentity | None, ...]
    constraints: tuple = ()

    def accepts_pattern(self, other):
        pattern = self.address.declared_type
        supplied = other.address.declared_type
        arguments = [None] * len(self.defaults)
        return (deduce_function_type(pattern, supplied, arguments)
                and pattern.substitute(arguments) == supplied)

    def instantiate(self, target, explicit):
        if len(explicit) > len(self.defaults):
            return None
        args = [*explicit, *([None] * (len(self.defaults) - len(explicit)))]
        signature = self.address.declared_type
        if target.words != ("auto",):
            if not target.layers or not deduce_function_type(signature._replace(layers=signature.layers[:-1]),
                                                             target._replace(layers=target.layers[:-1]), args):
                return None
        for i, default in enumerate(self.defaults):
            if args[i] is None:
                if default is None:
                    return None
                args[i] = default.substitute(args[:i])
                if args[i] is None:
                    return None
        if not constraints_satisfied(self.constraints, args):
            return None
        concrete = signature.substitute(args)
        if concrete is None:
            return None
        return self.address._replace(declared_type=concrete, specialization=(signature, self.constraints, tuple(args)))


class FunctionAddressSelection(NamedTuple):
    target: AliasIdentity
    addresses: frozenset[AddressArgument]
    unknown: bool
    take_address: bool
    templates: frozenset[TemplateFunction] = frozenset()
    explicit: tuple[AliasIdentity, ...] | None = None

    def substitute(self, arguments):
        target = self.target.substitute(arguments)
        if target is None:
            return None
        explicit = tuple(arg.substitute(arguments) for arg in self.explicit) if self.explicit is not None else None
        if explicit and None in explicit:
            return None
        return self._replace(explicit=explicit).resolve(target)

    def resolve(self, target):
        if target.is_dependent() or any(a.is_dependent() for a in self.explicit or ()):
            return self._replace(target=target)
        ordinary = self.matching(self.addresses, target) if self.explicit is None else set()
        if ordinary:
            return next(iter(ordinary)) if len(ordinary) == 1 else None
        viable = {}
        for template in self.templates:
            function = template.instantiate(target, self.explicit or ())
            if function is not None:
                for candidate in self.matching((function,), target):
                    viable[template] = candidate
        for template, candidate in viable.items():
            if all(other == template or (other.accepts_pattern(template) and (not template.accepts_pattern(other)
                                               or more_constrained(template.constraints, other.constraints)))
                   for other in viable):
                return candidate
        return None

    def matching(self, addresses, target):
        candidates = set()
        for function in addresses:
            identity = function.declared_type
            member = identity.layers[-1].operator == "::*"
            if member and not self.take_address:
                continue
            if not member and not self.take_address and target.layers and target.layers[-1].operator == "&":
                identity = identity._replace(layers=(*identity.layers[:-1], AliasLayer("&")))
            if target.words == ("auto",):
                if not self.unknown:
                    candidates.add(function._replace(declared_type=identity))
            elif identity == target:
                candidates.add(function._replace(declared_type=target))
            elif (identity.layers[-2].nonthrowing and target.layers and target.layers[-1].operator in ("*", "::*")):
                throwing = identity._replace(layers=(*identity.layers[:-2], identity.layers[-2]._replace(nonthrowing=False),
                                                    identity.layers[-1]))
                if throwing == target:
                    candidates.add(function._replace(declared_type=target))
        return candidates


class DeclaredObject(NamedTuple):
    declared_type: AliasIdentity
    constant: int | None = None
    origin: tuple[str, ...] | None = None
    address: AddressArgument | None = None
    receiver: tuple | None = None


class DeducedReturn(NamedTuple):
    origin: tuple
    parameters: tuple | None
    qualifiers: tuple
    constraints: tuple


class ClosureType(NamedTuple):
    position: int
    generic: bool

    def __bool__(self):
        return self.generic


class CallSignature(NamedTuple):
    minimum: int
    maximum: int | None
    template: bool
    result: object
    parameters: tuple | None
    return_type: AliasIdentity | None
    defaults: tuple
    constraints: tuple


class FunctionBinding(NamedTuple):
    kind: str
    # Overloads retain arity, template status and the result classification needed for member lookup.
    results: frozenset[CallSignature]
    operator_overloads: frozenset = frozenset()
    addresses: frozenset[AddressArgument] = frozenset()
    unknown_address: bool = False
    templates: frozenset[TemplateFunction] = frozenset()


class MemberPointerMatch(NamedTuple):
    name: str
    token_count: int
    prefix_count: int


class CppGrammar(ExpressionRules, ClassRules, OperatorRules, ConstraintRules, LambdaRules, ExceptionRules, AttributeRules):
    start = "translation_unit"
    tokens = tuple("""ASM GNU_ASM ELAB_KEY GNU_RESTRICT IDENT TYPE_NAME BUILTIN SPECIFIER NUMBER CHARACTER STRING HEADER MODULE IMPORT EXPORT PRIVATE DECLTYPE_SCOPE OP_TEMPLATE_OPEN REPLAY_BLOCK REPLAY_CTOR_ARGS DEFERRED_CTOR_ARGS DEFERRED_BODY EXTERN_TEMPLATE CTOR_TEMPLATE EXPLICIT_OPEN GNU_TYPEOF BUILTIN_BIT_CAST GUIDE_NAME MAKE_INTEGER_SEQ PACK_ELEMENT GNU_EXTENSION TYPE_TRANSFORM UNARY_TRAIT BINARY_TRAIT VARIADIC_TRAIT LINKAGE_EXTERN ALIGNAS GNU_ATTRIBUTE ATTR_OPEN ATTR_CLOSE ATTR_ATOM ATTR_NAME TRY CATCH THROW DO SWITCH CASE GOTO LABEL_NAME IF_CONSTEXPR
                      NAMESPACE INLINE SCOPE ENUM CLASS STRUCT UNION USING TYPEDEF TRUE FALSE NULLPTR THIS SIZEOF
                      ELLIPSIS PACK MEMBER_TYPE_SCOPE MEMBER_CLASS MEMBER_TEMPLATE TEMPLATE_MEMBER_SCOPE POINTER_TEMPLATE MEMBER_POINTER DOT_STAR ARROW_STAR UD_STRING REQUIRES NESTED_REQUIRES CONCEPT CONCEPT_NAME LAMBDA_OPEN NEW_TYPE_OPEN TYPE_PAREN ALIGNOF GNU_ALIGNOF TYPEID FOLD_OP OPERATOR CONVERSION_OPERATOR OP_ARRAY DEP_SCOPE NEW CO_AWAIT CO_YIELD CO_RETURN CTOR_NAME DTOR_NAME FINAL OVERRIDE VIRTUAL FRIEND FRIEND_KEY EXPLICIT DEFAULT DELETE DECLTYPE BLOCK_OPEN PARAM_OPEN GROUP_OPEN INIT_OPEN HEAD_END TEMPLATE TYPENAME ANGLE_OPEN ANGLE_CLOSE TEMPLATE_ID TEMPLATE_NAME PUBLIC PROTECTED STATIC_ASSERT FOR BREAK CONTINUE
                      STATIC_CAST CONST_CAST REINTERPRET_CAST DYNAMIC_CAST IF ELSE WHILE RETURN NOEXCEPT
                      ASSIGN_OP AND OR EQ REL SPACESHIP SHIFT INC DEC ARROW""".split())
    # In a bit-field width a ternary tail or new-expression consumes its initializer when possible.
    # A qualified name continues across :: even at the end of a requires-clause.
    # A conversion-type-id consumes all following type qualifiers and pointer attributes.
    precedence = (("nonassoc", "IF"), ("nonassoc", "ELSE"), ("nonassoc", "END_NAME"), ("right", "SCOPE", ":"), ("nonassoc", "END_WIDTH"), ("right", "=", "{"),
                  ("nonassoc", "END_TYPE"), ("right", "*", "&", "AND", "BUILTIN", "SPECIFIER", "INLINE", "VIRTUAL", "FRIEND", "EXPLICIT", "ATTR_OPEN", "ALIGNAS"), ("right", "GNU_ATTRIBUTE"))

    def p_empty(self, p):
        "empty :"
        p[0] = None

    def p_replay_context(self, p):
        """translation_unit : REPLAY_BLOCK block
                            | REPLAY_CTOR_ARGS ctor_arguments"""
        p[0] = p[2]

    def p_deferred_class_context(self, p):
        """block : DEFERRED_BODY
           ctor_arguments : DEFERRED_CTOR_ARGS"""
        # The enclosing class also completes before a nested member body is parsed.
        owner = next(sym for sym in p.stack if hasattr(sym, "pending_bodies"))
        marker = "REPLAY_BLOCK" if p.slice[1].type == "DEFERRED_BODY" else "REPLAY_CTOR_ARGS"
        p[0] = {}
        owner.pending_bodies.append((p[0], marker, p[1], [*self.inherited_stack, *p.stack]))

    def finish_member_bodies(self, bodies):
        for node, kind, tokens, scope in bodies:
            parser = copy(_state.parser)
            marker = copy(tokens[0])
            marker.type = kind
            marker.namespace = self.namespace(scope)
            saved = self.inherited_stack, self.source.lexpos, self.source.lineno
            self.inherited_stack = scope
            stream = self.parser_tokens(chain((marker,), tokens), parser)

            def next_token():
                token = next(stream, None)
                if token is not None:
                    self.source.lexpos, self.source.lineno = token.lexpos, token.lineno
                return token

            try:
                node.update(parser.parse(lexer=self.source, tokenfunc=next_token, tracking=True))
            finally:
                self.inherited_stack, self.source.lexpos, self.source.lineno = saved
        bodies.clear()

    def p_unit(self, p):
        "translation_unit : externals"
        unit = {"type": "TranslationUnit", "globalModuleFragment": None, "module": None,
                "declarations": [], "privateModuleFragment": None}
        declarations = unit["declarations"]
        for offset, node in p[1]:
            kind = node["type"]
            if kind == "GlobalModuleFragment":
                if unit["globalModuleFragment"] or unit["module"] or declarations:
                    raise self.source.error(offset, "global module fragment must come first")
                unit["globalModuleFragment"] = node
                declarations = node["declarations"]
            elif kind == "ModuleDeclaration":
                if unit["module"] or unit["declarations"]:
                    raise self.source.error(offset, "unexpected named module declaration")
                unit["module"] = node
                declarations = unit["declarations"]
            elif kind == "PrivateModuleFragment":
                module = unit["module"]
                if not module or not module["exported"] or module["partition"] or unit["privateModuleFragment"]:
                    raise self.source.error(offset, "private fragment requires a primary module interface")
                unit["privateModuleFragment"] = node
                declarations = node["declarations"]
            else:
                in_interface = bool(unit["module"] and unit["module"]["exported"] and not unit["privateModuleFragment"])
                self.check_module_context(node, offset, in_interface, unit["module"] is not None)
                declarations.append(node)
        if unit["globalModuleFragment"] and not unit["module"]:
            raise self.source.error(len(self.source.source), "expected a named module after global module fragment")
        p[0] = unit

    def check_module_context(self, node, offset, can_export, in_module):
        kind = node["type"]
        if kind == "ExportDeclaration":
            if not can_export:
                raise self.source.error(offset, "export requires module interface purview")
            for child in node["declarations"]:
                self.check_module_context(child, offset, False, in_module)
        elif kind == "NamespaceDefinition":
            for child in node["declarations"]:
                self.check_module_context(child, offset, can_export, in_module)
        elif kind == "ImportDeclaration" and node["kind"] == "partition" and not in_module:
            raise self.source.error(offset, "partition import requires a named module")

    def p_externals(self, p):
        """externals : empty
                     | externals external"""
        if len(p) == 2:
            p[0] = []
        else:
            p[1].append((p.lexpos(2), p[2]))
            p[0] = p[1]

    def p_external(self, p):
        """external : declaration
                    | MODULE ';'
                    | MODULE ':' PRIVATE ';'
                    | MODULE module_name partition_opt ';'
                    | EXPORT MODULE module_name partition_opt ';'"""
        if len(p) == 2:
            p[0] = p[1]
        elif len(p) == 3:
            p[0] = {"type": "GlobalModuleFragment", "declarations": []}
        elif p[2] == ":":
            p[0] = {"type": "PrivateModuleFragment", "declarations": []}
        else:
            p[0] = {"type": "ModuleDeclaration", "exported": p.slice[1].type == "EXPORT",
                    "name": p[len(p)-3], "partition": p[len(p)-2]}

    def p_module_name(self, p):
        """module_name : IDENT
                       | module_name '.' IDENT"""
        p[0] = p[1] if len(p) == 2 else p[1] + "." + p[3]

    def p_partition(self, p):
        """partition_opt : empty
                         | ':' module_name"""
        p[0] = None if len(p) == 2 else p[2]

    def p_language_linkage(self, p):
        """exportable : LINKAGE_EXTERN string_literal '{' declarations '}'
                      | LINKAGE_EXTERN string_literal declaration"""
        if any(not part.endswith('"') for part in p[2]):
            raise self.source.error(p.lexpos(2), "language linkage requires an unsuffixed string literal")
        block = len(p) == 6
        p[0] = {"type": "LinkageSpecification", "language": p[2], "block": block,
                "declarations": p[4] if block else [p[3]]}

    def p_import(self, p):
        """exportable : IMPORT module_name ';'
                      | IMPORT ':' module_name ';'
                      | IMPORT HEADER ';'"""
        p[0] = {"type": "ImportDeclaration", "target": p[len(p)-2],
                "kind": "partition" if len(p) == 5 else "header" if p.slice[2].type == "HEADER" else "module"}

    def p_asm_declaration(self, p):
        "asm_declaration : ASM '(' unsuffixed_string ')' ';'"
        p[0] = {"type": "AsmDeclaration", "parts": p[3]}

    def p_asm_export(self, p):
        """exportable : asm_export
           asm_export : asm_declaration
                      | attribute_specifier asm_export
           statement : asm_declaration"""
        p[0] = p[1] if len(p) == 2 else {**p[2], "attributes": [p[1], *p[2].get("attributes", [])]}

    def p_declaration(self, p):
        """declaration : exportable
                       | EXPORT exportable
                       | EXPORT '{' declarations '}'
                       | ';'"""
        if len(p) == 2:
            p[0] = {"type": "EmptyDeclaration"} if p[1] == ";" else p[1]
        else:
            if _UNNAMED_NAMESPACE in self.namespace(p.stack):
                raise self.source.error(p.lexpos(1), "export declaration within unnamed namespace")
            p[0] = {"type": "ExportDeclaration", "declarations": [p[2]] if len(p) == 3 else p[3]}

    def p_declarations(self, p):
        """declarations : empty
                        | declarations declaration"""
        if len(p) == 2:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    @staticmethod
    def namespace(stack):
        return next((s.namespace for s in reversed(stack) if hasattr(s, "namespace")), ())

    def store_binding(self, bindings, key, value):
        old = bindings.get(key)
        if isinstance(old, DeclaredObject) and isinstance(value, DeclaredObject):
            declared, previous = value.declared_type, old.declared_type
            if (declared.layers[-1:] == (AliasLayer("[]"),) and previous.layers
                    and previous.layers[-1].operator == "[]" and previous.layers[:-1] == declared.layers[:-1]
                    and previous.words == declared.words and previous.cv == declared.cv and previous.record == declared.record):
                value = value._replace(declared_type=previous, receiver=old.receiver)
        elif (isinstance(old, tuple) and isinstance(value, tuple) and old[0] == value[0] and value[0] in ("object", "function_type", "member_pointer")
              and old[1] == value[1] and old[2] and value[2][:1] == (ReceiverArray(None, omitted=True),)
              and isinstance(old[2][0], ReceiverArray) and old[2][1:] == value[2][1:]):
            value = old
        function_kinds = ("function", "function_template")
        old_kind, new_kind = self.binding_kind(old), self.binding_kind(value)
        if old_kind in function_kinds and new_kind in function_kinds:
            kind = "function_template" if "function_template" in (old_kind, new_kind) else "function"
            signatures = getattr(old, "results", frozenset()) | getattr(value, "results", frozenset())
            overloads = getattr(old, "operator_overloads", frozenset()) | getattr(value, "operator_overloads", frozenset())
            addresses = getattr(old, "addresses", frozenset()) | getattr(value, "addresses", frozenset())
            unknown = getattr(old, "unknown_address", False) or getattr(value, "unknown_address", False)
            templates = getattr(old, "templates", frozenset()) | getattr(value, "templates", frozenset())
            value = FunctionBinding(kind, signatures, overloads, addresses, unknown, templates) if signatures else kind
        bindings[key] = value

    def bind(self, stack, name, kind, *, declaration_offset=None, class_target=None, enum_tag=False, enum_target=None):
        if "::" in name:
            prefix, simple = name.rsplit("::", 1)
            scope = self.namespace_path(stack, prefix) if prefix else ()
            if isinstance(kind, DeclaredObject) and kind.origin is None:
                kind = kind._replace(origin=(*scope, simple))
            self.injected_only.discard((*scope, simple))
            self.store_binding(self.bindings, (*scope, simple), kind)
            return
        scopes = (s for s in reversed(stack) if hasattr(s, "locals") or hasattr(s, "namespace"))
        for symbol in scopes:
            if hasattr(symbol, "locals"):
                if declaration_offset is not None:
                    owner = next(scopes, None) if symbol.type == "BLOCK_OPEN" else symbol
                    reserved = getattr(owner, "control_names", ())
                    if owner is symbol and symbol.type in {"IF", "SWITCH", "WHILE", "FOR"}:
                        reserved = symbol.locals
                    if name in reserved:
                        raise self.source.error(declaration_offset, f"redeclaration of control variable {name!r}")
                self.store_binding(symbol.locals, name, kind)
                if enum_tag:
                    if not hasattr(symbol, "enum_tags"):
                        symbol.enum_tags = set()
                    symbol.enum_tags.add(name)
                if enum_target is not None:
                    if not hasattr(symbol, "enum_targets"):
                        symbol.enum_targets = {}
                    symbol.enum_targets[name] = enum_target
                if class_target is not None:
                    if not hasattr(symbol, "qualifier_aliases"):
                        symbol.qualifier_aliases = {}
                    symbol.qualifier_aliases[name] = class_target
                return
            if hasattr(symbol, "namespace"):
                break
        scope = self.namespace(stack)
        if isinstance(kind, DeclaredObject) and kind.origin is None:
            kind = kind._replace(origin=(*scope, name))
        for prefix in self.visible_namespace_paths(scope):
            key = (*prefix, name)
            if prefix == scope:
                self.injected_only.discard(key)
            elif key not in self.bindings:
                self.injected_only.add(key)
            elif key not in self.injected_only:
                continue  # Keep a direct declaration distinct from its inline-namespace competitors.
            self.store_binding(self.bindings, (*prefix, name), kind)
            if enum_tag:
                self.enum_tags.add((*prefix, name))
            if enum_target is not None:
                self.enum_targets[(*prefix, name)] = enum_target
            if class_target is not None:
                self.class_aliases[(*prefix, name)] = class_target

    def visible_namespace_paths(self, scope):
        visible = [()]
        for i, part in enumerate(scope):
            extended = [(*prefix, part) for prefix in visible]
            visible = visible + extended if scope[:i+1] in self.inline_namespaces else extended
        return visible

    def namespace_path(self, stack, spelling):
        parts = tuple(spelling.removeprefix("::").split("::"))
        if not spelling.startswith("::"):
            for symbol in reversed([*self.inherited_stack, *stack]):
                if parts[0] in getattr(symbol, "locals", {}):
                    local = getattr(symbol, "qualifier_aliases", {}).get(parts[0])
                    if local is not None:
                        return (*local, *parts[1:])
                    break
        base = () if spelling.startswith("::") else self.namespace(stack)
        for n in range(len(base), -1, -1):
            candidate = self.expand_class_alias(self.expand_namespace((*base[:n], *parts)), include_last=True)
            if candidate in self.namespaces or candidate in self.class_scopes:
                return candidate
        return parts

    def expand_namespace(self, parts, *, overloads=None):
        if not (self.using_namespaces or self.namespace_aliases or self.injected_namespaces or self.using_origins):
            return parts
        scope = ()
        for index, name in enumerate(parts):
            direct = (*scope, name)
            key = direct
            if scope in self.inline_children or (scope in self.using_namespaces and not self.known_namespace_member(direct)):
                imported = self.direct_member_keys(scope, name) if scope in self.inline_children else set()
                if not imported:
                    imported = self.imported_member_keys(scope, name)
                if len(imported) > 1:
                    functions = [self.bindings.get(candidate) for candidate in imported]
                    if index == len(parts)-1 and all(self.binding_kind(f) in ("function", "function_template") for f in functions):
                        if overloads is not None:
                            for function in functions:
                                self.store_binding(overloads, direct, function)
                        return direct
                    types = {self.common_type_origin(candidate) for candidate in imported}
                    if len(types) == 1:
                        imported = {min(imported)}
                    else:
                        offset = self.lookup_offset
                        remaining = len(parts)-index
                        if remaining <= len(self.lookup_components):
                            component, position = self.lookup_components[-remaining]
                            if component == name:
                                offset = position
                        raise self.source.error(offset, f"ambiguous imported name {name!r}")
                if imported:
                    key, = imported
            key = self.using_origins.get(key, key)
            alias = self.namespace_aliases.get(key)
            if alias is None and key not in self.namespaces:
                injected = self.injected_namespaces.get(key, ())
                if len(injected) == 1:
                    alias, = injected
            scope = alias if alias is not None else key
        return scope

    def sizeof_operand_type(self, stack, operand):
        operations = []
        while operand["type"] != "Type":
            if operand["type"] == "ParenthesizedExpression":
                operand = operand["expression"]
            elif operand["type"] == "SubscriptExpression":
                operations.append("*")
                operand = operand["base"]
            elif operand["type"] == "UnaryExpression" and operand["operator"] in ("*", "&"):
                if operand["operator"] == "&" and self.qualified_member_key(stack, operand["operand"]) in self.nonstatic_members:
                    break
                operations.append(operand["operator"])
                operand = operand["operand"]
            else:
                break
        if operand["type"] == "Type":
            alias = self.alias_identity(stack, operand)
            layout = TypeLayout.from_identity(alias) if alias else self.receiver_layout(self.object_binding(stack, operand))
        elif operand["type"] in ("NameExpression", "MemberExpression", "QualifiedMemberExpression"):
            if operand["type"] == "NameExpression":
                name = operand["name"]
                binding = self.lookup_binding(stack, name.removeprefix("::").split("::"), name.startswith("::"))
            else:
                binding = self.receiver_binding(stack, operand)
            layout = TypeLayout.from_identity(binding.declared_type) if isinstance(binding, DeclaredObject) else self.receiver_layout(binding)
        elif operand["type"] == "UnaryExpression" and operand["operator"] == "&":
            layout = self.receiver_layout(self.unary_receiver(stack, operand))
        elif operand["type"] == "StringLiteral" and "userDefined" not in operand:
            char = {"": "char", "u8": "char8_t", "u": "char16_t", "U": "char32_t", "L": "wchar_t"}
            size = _FUNDAMENTAL_BYTES[(char[operand.get("encodingPrefix", "")],)]
            layout = TypeLayout(size, size, (AliasLayer("[]", bound=string_array_extent(operand)),))
        else:
            return None
        if layout is None:
            return None
        layers = list(layout.layers)
        if layers and layers[-1].operator in ("&", "&&"):
            layers.pop()
        for op in reversed(operations):
            if op == "&":
                layers.append(AliasLayer("*"))
            elif layers and layers[-1].operator in ("[]", "*"):
                layers.pop()
            else:
                return None
        return layout._replace(layers=tuple(layers))

    @staticmethod
    def receiver_layout(binding):
        # Only the surrounding pointer and array layers contribute a known layout here.
        if isinstance(binding, FunctionBinding):
            return TypeLayout(None, None, ())
        if isinstance(binding, tuple) and binding[0] in ("object", "function_type", "member_pointer"):
            layers = tuple(AliasLayer("[]", bound=layer.bound) if isinstance(layer, ReceiverArray) else AliasLayer("*")
                           for layer in reversed(binding[2]))
            if binding[0] == "member_pointer":
                member = binding[1][1]
                function = isinstance(member, FunctionBinding) or (
                    isinstance(member, tuple) and member[0] == "function_type" and not member[2])
                return TypeLayout(16 if function else 8, 8, layers)
            return TypeLayout(None, None, layers)
        return None

    def array_bound_value(self, stack, expr, depth=0):
        """Fold operations whose result is independent of integer signedness on the pinned target."""
        while expr["type"] == "ParenthesizedExpression":
            expr = expr["expression"]
        if expr["type"] == "UnaryExpression" and expr["operator"] in ("sizeof", "alignof"):
            layout = self.sizeof_operand_type(stack, expr["operand"])
            if layout is None:
                return None
            return layout.measure(expr["operator"])
        if expr["type"] == "NameExpression":
            name = expr["name"]
            binding = self.lookup_binding(stack, name.removeprefix("::").split("::"), name.startswith("::"))
            if isinstance(binding, DeclaredObject):
                return binding.constant
            return binding[1] if isinstance(binding, tuple) and binding[0] == "constant_integer" else None
        if expr["type"] == "UnaryExpression" and expr["operator"] in ("+", "-"):
            operand = expr["operand"]
            while operand["type"] == "ParenthesizedExpression":
                operand = operand["expression"]
            if operand["type"] != "Literal":
                return None
            value = self.array_bound_value(stack, operand, depth + 1)
            if expr["operator"] == "+" or value is None:
                return value
            if value <= 0x7fffffff and not operand["raw"].lower().rstrip("l").endswith("u"):
                return -value
            return None
        if expr["type"] == "Literal" and "userDefined" not in expr:
            if expr["raw"] in ("true", "false"):
                return int(expr["raw"] == "true")
            spelling = expr["raw"].lower().replace("'", "").rstrip("ul")
            radix = 8 if spelling.startswith("0") and not spelling.startswith(("0x", "0b")) else 0
            try:
                return int(spelling, radix)
            except ValueError:
                return None
        if depth >= 64 or expr["type"] != "BinaryExpression" or expr["operator"] not in _BOUND_OPERATIONS:
            return None
        left = self.array_bound_value(stack, expr["left"], depth + 1)
        right = self.array_bound_value(stack, expr["right"], depth + 1)
        if left is None or right is None or min(left, right) < 0 or max(left, right) > 0x7fffffff:
            return None
        op = expr["operator"]
        if op in ("/", "%") and right == 0:
            return None
        value = _BOUND_OPERATIONS[op](left, right)
        return value if 0 <= value <= 0x7fffffff else None

    def type_argument_identity(self, stack, arg):
        if arg["type"] != "Type":
            return None
        obj = self.object_binding(stack, arg)
        scope = obj[1] if isinstance(obj, tuple) and obj[0] == "object" else None
        return self.alias_identity(stack, arg, record_scope=scope)

    def value_argument(self, stack, arg, target):
        if target is None:
            return None
        if target.layers and target.layers[-1].operator in ("*", "::*") and target.layers[-1].qualifiers:
            target = target.parameter_type()
        while arg["type"] == "ParenthesizedExpression":
            arg = arg["expression"]
        if arg["type"] == "Literal" and arg["raw"] == "nullptr":
            if target.words == ("auto",) and not target.layers:
                target = AliasIdentity(("nullptr_t",), frozenset(), ())
            elif not target.layers or target.layers[-1].operator not in ("*", "::*"):
                return None
            return AddressArgument(target, None)
        if target.layers or target.words == ("auto",):
            address = self.address_argument(stack, arg, target)
            if address is not None:
                return address
        return self.integral_argument(stack, arg, target)

    def address_argument(self, stack, arg, target, depth=0):
        if depth >= 64:
            return None
        while arg["type"] == "ParenthesizedExpression":
            arg = arg["expression"]
        if arg["type"] == "BinaryExpression" and arg["operator"] in ("+", "-"):
            auto = AliasIdentity(("auto",), frozenset(), ())
            pointer = self.address_argument(stack, arg["left"], auto, depth + 1)
            offset = arg["right"]
            if pointer is None and arg["operator"] == "+":
                pointer = self.address_argument(stack, arg["right"], auto, depth + 1)
                offset = arg["left"]
            if pointer is None or pointer.declared_type.layers[-1:] != (AliasLayer("*"),):
                return None
            distance = self.array_bound_value(stack, offset)
            if distance is None:
                return None
            result = pointer.displaced(distance if arg["operator"] == "+" else -distance)
            return result if result is None or target.words == ("auto",) else result._replace(declared_type=target)
        take_address = arg["type"] == "UnaryExpression" and arg["operator"] == "&"
        operand = arg["operand"] if take_address else arg
        subscripts = []
        while operand["type"] in ("ParenthesizedExpression", "SubscriptExpression"):
            if operand["type"] == "ParenthesizedExpression":
                operand = operand["expression"]
            else:
                index = self.array_bound_value(stack, operand["index"])
                if index is None:
                    return None
                subscripts.append(index)
                operand = operand["base"]
        if operand["type"] not in ("NameExpression", "TemplateId"):
            return None
        name = operand["name"]
        binding = self.lookup_binding(stack, name.removeprefix("::").split("::"), name.startswith("::"))
        if isinstance(binding, FunctionBinding) and not subscripts:
            explicit = None
            if "arguments" in operand:
                explicit = tuple(self.type_argument_identity(stack, arg) for arg in operand["arguments"])
                if None in explicit:
                    return None
            return FunctionAddressSelection(target, binding.addresses, binding.unknown_address, take_address,
                                            binding.templates, explicit).resolve(target)
        if isinstance(binding, AddressArgument) and not take_address and not subscripts:
            return binding if target.words == ("auto",) else binding._replace(declared_type=target)
        if not isinstance(binding, DeclaredObject) or binding.origin is None:
            return None
        obj, origin, indices = binding.declared_type, binding.origin, ()
        if obj.layers and obj.layers[-1].operator in ("&", "&&"):
            if binding.address is None:
                return None
            obj = obj._replace(layers=obj.layers[:-1])
            origin, indices = binding.address.origin, binding.address.indices
        for index in reversed(subscripts):
            if not obj.layers or obj.layers[-1].operator != "[]":
                return None
            obj = obj._replace(layers=obj.layers[:-1])
            indices += (index,)
        ref = target.layers and target.layers[-1].operator == "&"
        if take_address or ref:
            op = "*" if take_address else "&"
            layer = AliasLayer("::*", member_of=origin[:-1]) if take_address and origin in self.nonstatic_members else AliasLayer(op)
            deduced = obj._replace(layers=(*obj.layers, layer))
        elif obj.layers and obj.layers[-1].operator == "[]":
            deduced = obj._replace(layers=(*obj.layers[:-1], AliasLayer("*")))
            indices += (0,)
        elif binding.address is not None and not subscripts and (not binding.declared_type.layers
                or binding.declared_type.layers[-1].operator != "&"):
            return binding.address if target.words == ("auto",) else binding.address._replace(declared_type=target)
        else:
            return None
        return AddressArgument(deduced if target.words == ("auto",) else target, origin, indices)

    def integral_argument(self, stack, arg, target):
        if target is None or target.layers or target.record:
            return None
        if target.parameter is None and not integer_arguments.integral_type(target.words):
            return None
        result = self.integral_expression(stack, arg)
        if target.parameter is not None and result is not None:
            return DependentIntegralArgument(target.parameter, result)
        return integer_arguments.convert(result, target.words)

    def integral_expression(self, stack, arg, depth=0):
        if depth >= 64:
            return None
        kind = arg["type"]
        if kind == "ParenthesizedExpression":
            return self.integral_expression(stack, arg["expression"], depth + 1)
        if kind == "NameExpression":
            name = arg["name"]
            binding = self.lookup_binding(stack, name.removeprefix("::").split("::"), name.startswith("::"))
            if isinstance(binding, IntegralArgument):
                return binding
            if isinstance(binding, tuple) and binding[0] == "constant_integer":
                return IntegralArgument((), binding[1])
            if isinstance(binding, DeclaredObject) and binding.constant is not None:
                return IntegralArgument(binding.declared_type.words, binding.constant)
            return None
        if kind == "UnaryExpression" and arg["operator"] in ("sizeof", "alignof"):
            if arg["operand"]["type"] == "Type":
                identity = self.type_argument_identity(stack, arg["operand"])
                if identity is not None and identity.is_dependent():
                    return MeasureArgument(arg["operator"], identity)
            value = self.array_bound_value(stack, arg)
            return IntegralArgument(("int", "long", "unsigned"), value) if value is not None else None
        if kind == "UnaryExpression":
            value = self.integral_expression(stack, arg["operand"], depth + 1)
            return integer_arguments.evaluate(arg["operator"], value) if value is not None else None
        if kind == "BinaryExpression":
            left = self.integral_expression(stack, arg["left"], depth + 1)
            right = self.integral_expression(stack, arg["right"], depth + 1)
            if left is None or right is None:
                return None
            return integer_arguments.evaluate(arg["operator"], left, right)
        if kind != "Literal" or "userDefined" in arg:
            return None
        if arg["raw"].endswith("'"):
            char = character_argument(arg)
            return IntegralArgument((char[0],), char[1]) if char is not None else None
        value = self.array_bound_value(stack, arg)
        if value is None:
            return None
        words = integer_arguments.literal_words(arg["raw"], value)
        return IntegralArgument(words, value) if words else None

    def register_template_parameters(self, stack, primary, parameters):
        if not any("default" in p or p["type"] == "NonTypeTemplateParameter" for p in parameters):
            return
        previous = self.template_parameters.get(primary, ())
        signature = []
        locals_ = {}
        context = [*stack, SimpleNamespace(locals=locals_)]
        for index, param in enumerate(parameters):
            target = None
            default = previous[index].default if index < len(previous) else None
            if param["type"] == "TypeTemplateParameter":
                if "default" in param:
                    default = self.type_argument_identity(context, param["default"])
                binding = AliasIdentity((), frozenset(), (), parameter=index)
            elif param["type"] == "NonTypeTemplateParameter":
                target = self.type_argument_identity(context, param["parameterType"])
                if "default" in param and target is not None:
                    default = self.value_argument(context, param["default"], target)
                if target is None:
                    binding = "value"
                elif target.layers and target.layers[-1].operator in ("*", "::*", "&"):
                    binding = AddressArgument(target, None, parameter=index)
                else:
                    binding = IntegralArgument(target.words or ("auto",), None, index)
            else:
                binding = "type_template"
            if param.get("name"):
                locals_[param["name"]] = binding
            signature.append(TemplateParameter(target, default, param.get("pack", False)))
        self.template_parameters[primary] = signature

    def template_argument_identities(self, stack, primary, args):
        arguments = []
        signature = self.template_parameters.get(primary, ())
        for index, arg in enumerate(args):
            formal = signature[min(index, len(signature)-1)] if signature else None
            if formal is not None and formal.value_type is not None:
                parameter_type = formal.value_type.substitute(arguments)
                item = self.value_argument(stack, arg, parameter_type)
            else:
                item = self.type_argument_identity(stack, arg)
            if item is None:
                return None
            arguments.append(item)
        for formal in signature[len(arguments):]:
            if formal.pack:
                break
            if formal.default is None:
                return None
            item = formal.default.substitute(arguments)
            if item is None:
                return None
            arguments.append(item)
        return tuple(arguments)

    def alias_identity(self, stack, target, *, record_scope=None):
        cv = frozenset(s for s in target["specifiers"] if s in ("const", "volatile"))
        base = [s for s in target["specifiers"] if s not in ("const", "volatile")]
        if len(base) == 1 and isinstance(base[0], dict):
            spec = base[0]
            if spec["type"] not in ("TypeName", "ElaboratedType"):
                return None
            name = spec["name"]
            alias = self.lookup_binding(stack, name.removeprefix("::").split("::"), name.startswith("::"))
            if "arguments" in spec:
                primary = self.namespace_path(stack, name)
                if alias != "type_template" or primary not in self.class_scopes:
                    return None
                arguments = self.template_argument_identities(stack, primary, spec["arguments"])
                if arguments is None:
                    return None
                alias = AliasIdentity((), frozenset(), (), RecordIdentity(primary, arguments))
            elif isinstance(alias, ReceiverType):
                alias = alias.identity
            elif alias == "type":
                scope = record_scope if record_scope is not None else self.namespace_path(stack, name)
                if scope not in self.class_scopes:
                    return None
                alias = AliasIdentity((), frozenset(), (), RecordIdentity(scope))
            if not isinstance(alias, AliasIdentity):
                return None
            alias = alias.qualified(cv)
            return self.apply_alias_declarator(stack, target, alias)
        elif base and all(isinstance(s, str) and s in BUILTINS for s in base):
            words = ["signed" if s in ("__signed", "__signed__") else s for s in base]
            if all(s in {"signed", "unsigned", "short", "long", "int"} for s in words):
                words = [s for s in words if s not in ("int", "signed")] + ["int"]
            words = tuple(sorted(words))
        else:
            return None
        return self.apply_alias_declarator(stack, target, AliasIdentity(words, cv, ()))

    def function_type_layer(self, stack, operator):
        parameters = []
        variadic = False
        for param in operator["parameters"]:
            if param["type"] == "Ellipsis":
                variadic = True
                continue
            if param.get("pack") or "parameterType" not in param:
                return None
            item = self.type_argument_identity(stack, param["parameterType"])
            if item is None:
                return None
            parameters.append(item.parameter_type())
        if parameters == [AliasIdentity(("void",), frozenset(), ())]:
            parameters.clear()
        noexcept = operator.get("noexcept", False)
        if isinstance(noexcept, dict):
            noexcept = True if noexcept["type"] == "EmptyThrowSpecification" else self.array_bound_value(stack, noexcept)
            if noexcept is None:
                return None
        return AliasLayer("()", frozenset(operator.get("qualifiers", ())), parameters=tuple(parameters),
                          variadic=variadic, nonthrowing=bool(noexcept))

    def apply_alias_declarator(self, stack, target, base):
        layers = list(base.layers)
        operators = reversed(target["declarator"]) if "declarator" in target else target.get("indirections", ())
        for item in operators:
            if isinstance(item, dict) and item.get("type") == "FunctionOperator":
                layer = self.function_type_layer(stack, item)
                if layer is None or "trailingReturnType" in item:
                    return None
                layers.append(layer)
                continue
            if isinstance(item, dict) and item.get("type") == "ArrayOperator":
                if item.keys() - {"type", "size"}:
                    return None
                bound = item["size"]
                extent = self.array_bound_value(stack, bound) if bound is not None else None
                if bound is not None and extent is None:
                    return None
                layers.append(AliasLayer("[]", bound=extent))
                continue
            member_of = None
            if isinstance(item, dict):
                if item.keys() - {"type", "operator", "qualifiers", "class"} or "operator" not in item:
                    return None
                op, qualifiers = item["operator"], frozenset(item.get("qualifiers", ()))
                if "class" in item:
                    member_of = self.namespace_path(stack, item["class"])
                    if op != "*" or member_of not in self.class_scopes:
                        return None
                    op = "::*"
            else:
                op, qualifiers = item, frozenset()
            append_alias_layer(layers, AliasLayer(op, qualifiers, member_of=member_of))
        return base._replace(layers=tuple(layers))

    def common_type_origin(self, key):
        binding = self.bindings.get(key)
        if isinstance(binding, AliasIdentity):
            return binding
        if isinstance(binding, ReceiverType):
            return binding.identity if binding.identity is not None else key
        if key in self.class_aliases:
            return AliasIdentity((), frozenset(), (), RecordIdentity(self.class_aliases[key]))
        if key in self.class_scopes:
            return AliasIdentity((), frozenset(), (), RecordIdentity(key))
        return key

    def nominated_levels(self, scope, local_directives):
        """Yield each enclosing scope with the directives that participate at that level."""
        nominated = {}
        for size in range(len(scope), -1, -1):
            parent = scope[:size]
            pending = list(local_directives) if size == len(scope) else []
            for child in self.inline_namespace_set(parent):
                pending.extend(self.using_namespaces.get(child, ()))
            seen = set()
            while pending:
                ns = pending.pop()
                if ns in seen:
                    continue
                seen.add(ns)
                ancestor = parent
                while ns[:len(ancestor)] != ancestor:
                    ancestor = ancestor[:-1]
                nominated.setdefault(ancestor, set()).add(ns)
                for child in self.inline_namespace_set(ns):
                    pending.extend(self.using_namespaces.get(child, ()))
            yield parent, nominated.get(parent, ())

    def direct_member_keys(self, scope, name):
        matches = set()
        for ns in self.inline_namespace_set(scope):
            key = (*ns, name)
            if key in self.namespaces or key in self.namespace_aliases:
                matches.add(self.namespace_aliases.get(key, key))
            elif key in self.bindings and key not in self.injected_only:
                matches.add(self.using_origins.get(key, key))
        return matches

    def imported_member_keys(self, scope, name):
        """Search each nominated namespace, stopping at the first declaring scope on each path."""
        pending = [target for ns in self.inline_namespace_set(scope) for target in self.using_namespaces.get(ns, ())]
        seen, found = {scope}, set()
        while pending:
            parent = pending.pop()
            if parent in seen:
                continue
            seen.add(parent)
            matches = self.direct_member_keys(parent, name)
            if matches:
                found.update(matches)
            else:
                for ns in self.inline_namespace_set(parent):
                    pending.extend(self.using_namespaces.get(ns, ()))
        return found

    def known_namespace_member(self, key):
        return (key in self.namespaces or key in self.bindings or key in self.namespace_aliases
                or key in self.injected_namespaces)

    def expand_class_alias(self, path, *, include_last=False):
        expanded = set()
        while self.class_aliases:
            for size in range(len(path) if include_last else len(path)-1, 0, -1):
                prefix = path[:size]
                target = self.class_aliases.get(prefix)
                if target is not None and target != prefix and prefix not in expanded:
                    expanded.add(prefix)
                    path = (*target, *path[size:])
                    break
            else:
                break
        return path

    @staticmethod
    def enumerator_binding(target, name):
        if target is None:
            return None
        records, key = target
        enum = records.get(key)
        if enum and "bindings" in enum:
            return enum["bindings"].get(name)
        if enum and any(item["name"] == name for item in enum["enumerators"] or []):
            return "value"
        return None

    @staticmethod
    def binding_kind(binding):
        if isinstance(binding, DeclaredObject):
            return binding.receiver or "value"
        if isinstance(binding, (IntegralArgument, AddressArgument)):
            return "value"
        if isinstance(binding, AliasIdentity):
            return "type"
        if isinstance(binding, FunctionBinding):
            return binding.kind
        if isinstance(binding, tuple) and binding[0] == "constant_integer":
            return "value"
        if binding == "dependent_value":
            return "value"
        if isinstance(binding, ReceiverType):
            return "type"
        return binding

    def lookup(self, stack, parts, absolute, *, enum_tag=False, enum_target=False):
        binding = self.lookup_binding(stack, parts, absolute, enum_tag=enum_tag, enum_target=enum_target)
        return binding if enum_target else self.binding_kind(binding)

    def lookup_binding(self, stack, parts, absolute, *, enum_tag=False, enum_target=False):
        if self.inherited_stack:
            stack = [*self.inherited_stack, *stack]
        def in_namespaces(scopes, names=parts):
            pending = list(scopes)
            seen = set()
            while pending:
                scope = pending.pop()
                if scope in seen:
                    continue
                seen.add(scope)
                overloads = {}
                key = self.expand_class_alias(self.expand_namespace((*scope, *names), overloads=overloads))
                if key in overloads and not (enum_tag or enum_target):
                    return overloads[key]
                if enum_tag and key in self.enum_tags:
                    return "enum"
                if not enum_tag and key in self.bindings:
                    return self.enum_targets.get(key) if enum_target else self.bindings[key]
                if len(key) > 1 and not enum_tag and not enum_target:
                    binding = self.enumerator_binding(self.enum_targets.get(key[:-1]), key[-1])
                    if binding is not None:
                        return binding
                pending.extend(self.using_namespaces.get(scope, ()))
                pending.extend(self.base_scopes.get(scope, ()))
            return None

        unqualified = len(parts) == 1 and not absolute
        local_directives = set()
        if not absolute:
            for symbol in reversed(stack):
                if len(parts) > 1 and parts[0] in getattr(symbol, "locals", {}):
                    target = getattr(symbol, "qualifier_aliases", {}).get(parts[0])
                    if target is not None:
                        return in_namespaces([target], parts[1:])
                    if self.binding_kind(symbol.locals[parts[0]]) == "type":
                        enum = getattr(symbol, "enum_targets", {}).get(parts[0])
                        if len(parts) == 2 and not enum_tag and not enum_target:
                            return self.enumerator_binding(enum, parts[1])
                        return None
                if len(parts) == 1:
                    bindings = getattr(symbol, "locals", {})
                    if enum_tag:
                        if parts[0] in getattr(symbol, "enum_tags", ()):
                            return "enum"
                        if self.binding_kind(bindings.get(parts[0])) == "type" or parts[0] in getattr(symbol, "template_types", ()):
                            return None
                    elif parts[0] in bindings:
                        return getattr(symbol, "enum_targets", {}).get(parts[0]) if enum_target else bindings[parts[0]]
                    if parts[0] in getattr(symbol, "template_values", ()):
                        return None if enum_target else "value"
                    if parts[0] in getattr(symbol, "template_names", ()):
                        return None if enum_target else "type_template"
                    if parts[0] in getattr(symbol, "template_types", ()):
                        return None if enum_target else "type"
                directives = getattr(symbol, "using_namespaces", ())
                if unqualified:
                    local_directives.update(directives)
                elif directives and (binding := in_namespaces(directives)):
                    return binding
        scope = () if absolute else self.namespace(stack)
        if unqualified and (self.using_namespaces or local_directives):
            name = parts[0]
            for parent, nominated in self.nominated_levels(scope, local_directives):
                if parent in self.class_scopes:
                    key = self.member_key(parent, name)
                    if key is not None:
                        if enum_tag:
                            return "enum" if key in self.enum_tags else None
                        return self.enum_targets.get(key) if enum_target else self.bindings[key]
                keys = set()
                for ns in (parent, *nominated):
                    for child in self.inline_namespace_set(ns):
                        key = (*child, name)
                        if key in self.bindings and key not in self.injected_only:
                            keys.add(self.using_origins.get(key, key))
                if not keys:
                    continue
                if len(keys) > 1 and len({self.common_type_origin(k) for k in keys}) > 1:
                    merged = {}
                    for key in keys:
                        binding = self.bindings[key]
                        if self.binding_kind(binding) not in ("function", "function_template"):
                            return None if enum_target or enum_tag else "ambiguous"
                        self.store_binding(merged, name, binding)
                    return None if enum_target or enum_tag else merged[name]
                key = min(keys)
                if enum_tag:
                    return "enum" if key in self.enum_tags else None
                return self.enum_targets.get(key) if enum_target else self.bindings[key]
            return None
        for n in range(len(scope), -1, -1):
            if binding := in_namespaces([scope[:n]]):
                return binding
        return None

    def has_dependent_qualifier(self, stack, spelling):
        first = spelling.split("::", 1)[0]
        return bool(first) and any(first in getattr(sym, "template_types", ()) for sym in [*self.inherited_stack, *stack])

    def member_key(self, scope, name):
        if scope in self.ambiguous_specializations:
            raise self.source.error(self.lookup_offset, "ambiguous class template partial specialization")
        pending, visited = [scope], set()
        while pending:
            scope = pending.pop()
            if scope not in visited:
                visited.add(scope)
                key = (*scope, name)
                if key in self.bindings:
                    return key
                pending.extend(self.base_scopes.get(scope, ()))
        return None

    def member_binding(self, scope, name, *, raw=False):
        binding = self.bindings.get(self.member_key(scope, name))
        if raw:
            return binding.receiver if isinstance(binding, DeclaredObject) and binding.receiver else binding
        return self.binding_kind(binding)

    def receiver_array(self, stack, size):
        return ReceiverArray(self.array_bound_value(stack, size)) if size is not None else ReceiverArray(None, omitted=True)

    def receiver_layers(self, stack, operators):
        """Array and pointer layers in order from the identifier towards its base type."""
        layers = []
        for op in operators:
            if isinstance(op, dict):
                if op.get("type") == "ArrayOperator":
                    layers.append(self.receiver_array(stack, op["size"]))
                    continue
                if "operator" not in op or "class" in op:
                    return None
                op = op["operator"]
            if op == "*":
                layers.append("pointer")
        return tuple(layers)

    def declared_binding(self, stack, target, *, parameter=False):
        kind = self.object_binding(stack, target)
        receiver = kind if isinstance(kind, tuple) and kind[0] in ("object", "function_type", "member_pointer") else None
        if (kind == "value" or receiver) and "auto" not in target["specifiers"]:
            specs = [s for s in target["specifiers"] if s not in (
                "static", "extern", "constexpr", "inline", "thread_local", "constinit", "mutable")]
            record = receiver[1] if receiver and receiver[0] == "object" else None
            identity = self.alias_identity(stack, {**target, "specifiers": specs}, record_scope=record)
            if identity is not None:
                if "constexpr" in target["specifiers"]:
                    identity = identity.qualified(frozenset({"const"}))
                if parameter and identity.layers and identity.layers[-1].operator in ("[]", "()"):
                    identity = identity.parameter_type()
                    if receiver:
                        layers = receiver[2]
                        if layers and isinstance(layers[0], ReceiverArray):
                            layers = layers[1:]
                        receiver = (*receiver[:2], ("pointer", *layers))
                kind = DeclaredObject(identity, receiver=receiver)
        return kind

    def object_binding(self, stack, target):
        operators = target.get("declarator")
        if operators is None and any(isinstance(op, dict) and "class" in op for op in target["indirections"]):
            operators = self.pointer_operators(target["indirections"])
        for index, op in enumerate(operators or ()):
            if "class" not in op and op["type"] != "FunctionOperator":
                continue
            layers = self.receiver_layers(stack, operators[:index])
            if layers is None:
                return "value"
            base = {"type": "Type", "specifiers": target["specifiers"], "indirections": []}
            inner = self.derived_type(base, operators[index+1:])
            if op["type"] == "FunctionOperator":
                parameters = {arg["name"]: self.object_binding(stack, arg["parameterType"])
                              for arg in op["parameters"] if arg.get("name")}
                signature = self.function_binding(stack, "", "function", op, inner, SimpleNamespace(locals=parameters))
                return ("function_type", signature, layers)
            owner = (self.specialization_scope(stack, op["owner"]) if "owner" in op
                     else self.namespace_path(stack, op["class"]))
            member = self.object_binding(stack, inner)
            return ("member_pointer", (owner, member), layers)
        specs = [s for s in target["specifiers"] if s not in ("const", "volatile", "static", "extern", "inline", "constexpr", "consteval", "virtual", "friend")]
        if specs in (["void"], [{"type": "TypeName", "name": "void"}]) and not target.get("declarator") and not target.get("indirections"):
            return "void"
        if len(specs) != 1 or not isinstance(specs[0], dict):
            return "value"
        spec = specs[0]
        receiver = None
        if spec["type"] == "Decltype" and isinstance(spec["operand"], dict):
            receiver = self.receiver_binding(stack, spec["operand"])
        elif spec["type"] == "TypeName" and "arguments" not in spec:
            name = spec["name"]
            receiver = self.lookup_binding(stack, name.removeprefix("::").split("::"), name.startswith("::"))
        elif spec["type"] == "QualifiedType" and "arguments" not in spec:
            scope = self.base_scope(stack, spec["qualifier"])
            receiver = self.member_binding(scope, spec["name"], raw=True) if scope else None
        layers = self.receiver_layers(stack, target.get("declarator", target.get("indirections", ())))
        if layers is None:
            return "value"
        if spec["type"] == "ClassDeclaration":
            scope = (self.namespace_path(stack, spec["name"]) if spec["name"]
                     else (*self.namespace(stack), f"<unnamed class at {spec['startOffset']}>"))
            return ("object", scope, layers)
        if isinstance(receiver, ReceiverType):
            receiver = receiver.receiver
        if isinstance(receiver, tuple) and receiver[0] in _INDIRECT_BINDINGS:
            return (receiver[0], receiver[1], layers + receiver[2])
        if spec["type"] == "DependentType" or (spec["type"] == "TypeName" and self.has_dependent_qualifier(stack, spec["name"])):
            return "dependent_value"
        if spec["type"] not in {"TypeName", "ElaboratedType", "QualifiedType"}:
            return "value"
        scope = self.base_scope(stack, specs[0])
        if scope in self.class_scopes:
            return ("object", scope, layers)
        return "value"

    @staticmethod
    def has_placeholder_parameter(parameters):
        return any(arg.get("parameterType") and any(
            spec == "auto" or isinstance(spec, dict) and spec["type"] == "ConstrainedPlaceholder"
            for spec in arg["parameterType"]["specifiers"]
        ) for arg in parameters or [])

    def initializer_receiver(self, stack, node):
        if node is None:
            return None
        if node["type"] == "CopyInitializer":
            node = node["value"]
        elif node["type"] in {"DirectInitializer", "InitializerList"}:
            values = node.get("arguments", node.get("elements", []))
            if len(values) != 1:
                return None
            node = values[0]
        binding = self.receiver_binding(stack, node)
        return binding if isinstance(binding, tuple) and binding[0] in _INDIRECT_BINDINGS else None

    def concept_constraint(self, stack, parameters, expression, position):
        if any(p["type"] != "TypeTemplateParameter" or p.get("pack") for p in parameters):
            return None
        locals_ = {p["name"]: AliasIdentity((), frozenset(), (), parameter=i)
                   for i, p in enumerate(parameters) if p.get("name")}
        return self.normalized_constraint([*stack, SimpleNamespace(locals=locals_)], expression, (position,))

    def lambda_return_key(self, intro, parameters, explicit_template):
        return ClosureType(intro.lexpos, explicit_template or self.has_placeholder_parameter(parameters))

    def normalized_constraint(self, stack, node, origin):
        while node["type"] == "ParenthesizedExpression":
            node = node["expression"]
        if node["type"] == "BinaryExpression" and node["operator"] in ("&&", "||"):
            return Constraint(node["operator"], tuple(self.normalized_constraint(stack, node[key], (*origin, key))
                                                      for key in ("left", "right")))
        if node["type"] == "ConceptId":
            name = node["name"]
            concept = self.lookup_binding(stack, name.removeprefix("::").split("::"), name.startswith("::"))
            if isinstance(concept, tuple) and concept[0] == "concept" and concept[3] is not None:
                args = tuple(self.type_argument_identity(stack, arg) for arg in node["arguments"])
                if None not in args and len(args) == concept[4]:
                    return concept[3].mapped(args)
        return Constraint("atom", (origin, self.integral_expression(stack, node)))

    def function_binding(self, stack, name, kind, function, return_type, symbol, template_params=None, requires=()):
        params = function["parameters"]
        if len(params) == 1 and params[0].get("parameterType") == {"type": "Type", "specifiers": ["void"], "indirections": []}:
            params = []
        fixed = [arg for arg in params if arg["type"] != "Ellipsis" and not arg.get("pack")]
        minimum = sum(arg["default"] is None for arg in fixed)
        maximum = len(fixed) if len(fixed) == len(params) else None
        if "trailingReturnType" in function:
            result = self.object_binding([*stack, symbol], function["trailingReturnType"])
        else:
            result = self.object_binding(stack, return_type)
        overloads = frozenset()
        if name.rsplit("::", 1)[-1] in _RECEIVER_OPERATORS:
            operands = tuple(self.object_binding(stack, arg["parameterType"]) for arg in fixed)
            scope = getattr(symbol, "namespace", self.namespace(stack))
            is_member = scope in self.class_scopes and "friend" not in return_type["specifiers"]
            if is_member:
                operands = (("object", scope, ()), *operands)
            formal = tuple(self.type_argument_identity(stack, arg["parameterType"]) for arg in fixed)
            if is_member:
                formal = (AliasIdentity((), frozenset(), (), RecordIdentity(scope)), *formal)
            overloads = frozenset({(is_member, operands, result, formal)})
        addresses = frozenset()
        templates = frozenset()
        defaults = []
        context = stack
        constraints = []
        if template_params and all(p["type"] == "TypeTemplateParameter" and not p.get("pack") for p in template_params):
            locals_ = {}
            context = [*stack, SimpleNamespace(locals=locals_)]
            for i, param in enumerate(template_params):
                defaults.append(self.type_argument_identity(context, param["default"]) if "default" in param else None)
                if param.get("name"):
                    locals_[param["name"]] = AliasIdentity((), frozenset(), (), parameter=i)
                if "constraint" in param:
                    key = param.get("name") or f"<parameter {i}>"
                    locals_[key] = AliasIdentity((), frozenset(), (), parameter=i)
                    argument = {"type": "Type", "specifiers": [{"type": "TypeName", "name": key}], "indirections": []}
                    constraint = param["constraint"]
                    concept = {"type": "ConceptId", "name": constraint["name"], "arguments": [argument, *constraint.get("arguments", [])]}
                    constraints.append(self.normalized_constraint(context, concept, (symbol.lexpos, i)))
        constraints.extend(self.normalized_constraint(context, expr, (symbol.lexpos, "requires", i))
                           for i, expr in enumerate(requires) if expr is not None)
        constraints = tuple(constraints)
        layer = self.function_type_layer(context, function)
        identity = None
        if name and (kind == "function" or defaults):
            ret = function.get("trailingReturnType", return_type)
            specs = [s for s in ret["specifiers"] if s not in ("constexpr", "consteval", "static", "inline", "extern",
                                                               "friend", "virtual", "explicit", "__inline", "__inline__")]
            record = result[1] if isinstance(result, tuple) and result[0] == "object" else None
            identity = self.alias_identity(context, {**ret, "specifiers": specs}, record_scope=record)
            if identity is not None and identity.words != ("auto",):
                if layer is not None:
                    scope = getattr(symbol, "namespace", self.namespace(stack))
                    if "::" in name:
                        scope = self.namespace_path(stack, name.rsplit("::", 1)[0])
                    member = scope in self.class_scopes and not any(s in ("static", "friend") for s in return_type["specifiers"])
                    pointer = AliasLayer("::*", member_of=scope) if member else AliasLayer("*")
                    origin = (*scope, name.rsplit("::", 1)[-1])
                    address = AddressArgument(identity._replace(layers=(*identity.layers, layer, pointer)), origin)
                    if defaults:
                        templates = frozenset({TemplateFunction(address, tuple(defaults), constraints)})
                    else:
                        addresses = frozenset({address})
        parameters = layer.parameters if layer is not None else None
        placeholder = return_type["specifiers"]
        if name and "trailingReturnType" not in function and (
                "auto" in placeholder or {"type": "Decltype", "operand": "auto"} in placeholder):
            scope = getattr(symbol, "namespace", self.namespace(stack))
            if "::" in name:
                scope = self.namespace_path(stack, name.rsplit("::", 1)[0])
            result = DeducedReturn((*scope, name.rsplit("::", 1)[-1]), parameters, tuple(function["qualifiers"]), constraints)
            symbol.deduced_return = result
            overloads = frozenset((member, operands, result, formal) for member, operands, _, formal in overloads)
        call = CallSignature(minimum, maximum, kind == "function_template", result, parameters, identity,
                             tuple(defaults), constraints)
        return FunctionBinding(kind, frozenset({call}), overloads, addresses, bool(name and not addresses and not templates), templates)

    def resolved_return(self, result, identity, type_only):
        if isinstance(result, (DeducedReturn, ClosureType)):
            values = {t if type_only else r for r, t in self.deduced_returns.get(result, ())}
            return next(iter(values)) if len(values) == 1 else None
        return identity if type_only else result

    def call_result_binding(self, stack, function, args, *, explicit_args=False, type_only=False):
        if isinstance(function, tuple) and function[0] == "closure" and not function[2]:
            return self.resolved_return(function[1], None, type_only)
        if isinstance(function, tuple) and function[0] == "function_type" and function[2] in ((), ("pointer",)):
            function = function[1]
        if not isinstance(function, FunctionBinding):
            return None
        for arg in args:
            if arg["type"] == "PackExpansion":
                return None
            if arg["type"] == "NameExpression" and self.receiver_binding(stack, arg) == "dependent_value":
                return None
        viable = [f for f in function.results if (not explicit_args or f.template) and f.minimum <= len(args)
                  and (f.maximum is None or len(args) <= f.maximum)]
        results = {self.resolved_return(f.result, f.return_type, type_only) for f in viable}
        if len(results) < 2:
            return next(iter(results), None)
        actual = [self.argument_identity(stack, arg) for arg in args]
        if None in actual:
            return None
        ranked = []
        for f in viable:
            params = f.parameters
            if params is None or len(params) < len(args):
                return None
            deduced = [None] * len(f.defaults)
            if f.template:
                if not f.defaults:
                    return None
                for formal, supplied in zip(params, actual):
                    if formal.layers and formal.layers[-1].operator in ("&", "&&"):
                        formal = formal._replace(layers=formal.layers[:-1])
                    if supplied.layers and supplied.layers[-1].operator in ("&", "&&"):
                        supplied = supplied._replace(layers=supplied.layers[:-1])
                    if not deduce_function_type(formal, supplied, deduced):
                        break
                else:
                    for i, default in enumerate(f.defaults):
                        if deduced[i] is None and default is not None:
                            deduced[i] = default.substitute(deduced[:i])
                    if None not in deduced and constraints_satisfied(f.constraints, deduced):
                        params = tuple(t.substitute(deduced) for t in params)
                        if None not in params:
                            ranks = [self.conversion_rank(a, t, e) for a, t, e in zip(actual, params, args)]
                            if None not in ranks:
                                ranked.append((f, ranks, deduced))
                continue
            ranks = [self.conversion_rank(a, t, e) for a, t, e in zip(actual, params, args)]
            if None not in ranks:
                ranked.append((f, ranks, deduced))
        best = set()
        for f, ranks, deduced in ranked:
            if any(other != ranks and all(a <= b for a, b in zip(other, ranks)) for _, other, _ in ranked):
                continue
            if f.template and any(other == ranks and (not g.template or
                    (f.parameters == g.parameters and more_constrained(g.constraints, f.constraints))) for g, other, _ in ranked):
                continue
            identity = f.return_type.substitute(deduced) if type_only and f.return_type else None
            best.add(self.resolved_return(f.result, identity, type_only))
        return next(iter(best)) if len(best) == 1 else None

    @staticmethod
    def best_receiver(ranked):
        best = {result for result, ranks in ranked if not any(
            other != ranks and all(a <= b for a, b in zip(other, ranks)) for _, other in ranked)}
        return next(iter(best)) if len(best) == 1 else None

    @staticmethod
    def standard_rank(source, target):
        if source.layers and source.layers[-1].operator in ("&", "&&"):
            source = source._replace(layers=source.layers[:-1])
        by_reference = target.layers and target.layers[-1].operator in ("&", "&&")
        if by_reference:
            target = target._replace(layers=target.layers[:-1])
        else:
            source = source.parameter_type()
            target = target.parameter_type()
        if source == target:
            return 0
        if (source.layers == target.layers and source.words == target.words and source.record == target.record
                and source.parameter is None and target.parameter is None and source.cv <= target.cv
                and (len(source.layers) <= 1 or all("const" in layer.qualifiers for layer in source.layers[:-1]))):
            return 1
        if source.layers or target.layers or source.record or target.record or target.parameter is not None:
            return None
        floats = (("float",), ("double",), ("double", "long"))
        if not (source.words in floats or integer_arguments.integral_type(source.words)):
            return None
        if source.words == ("float",) and target.words == ("double",):
            return 2
        if integer_arguments.integral_type(source.words) and integer_arguments.promoted(source.words) == target.words:
            return 2
        return 3 if target.words in floats or integer_arguments.integral_type(target.words) else None

    def conversion_rank(self, source, target, expr):
        if target.layers and target.layers[-1].operator in ("&", "&&"):
            while expr["type"] == "ParenthesizedExpression":
                expr = expr["expression"]
            lvalue = expr["type"] in ("NameExpression", "SubscriptExpression", "MemberExpression")
            temporary = expr["type"] in ("Literal", "TypeConstruction")
            if target.layers[-1].operator == "&&" and lvalue:
                return None
            if target.layers[-1].operator == "&" and temporary and "const" not in target.cv:
                return None
            if not source.cv <= target.cv and source.words == target.words:
                return None
        rank = self.standard_rank(source, target)
        if rank is not None:
            return rank
        if source.layers and source.layers[-1].operator in ("&", "&&"):
            source = source._replace(layers=source.layers[:-1])
        if target.layers and target.layers[-1].operator in ("&", "&&"):
            target = target._replace(layers=target.layers[:-1])
        if (source.record and target.record and source.layers == target.layers and len(source.layers) <= 1
                and self.derives_from(source.record.scope, target.record.scope)):
            return 3
        if source.record:
            conversions = self.implicit_conversions.get(source.record.scope, ())
            ranks = [r for t in conversions if (r := self.standard_rank(t, target)) is not None]
            if ranks:
                # Compare the second standard conversion only for a common conversion function.
                return 4 + min(ranks) if len(conversions) == 1 else 4
        if target.record and any(self.standard_rank(source, t) is not None for t in self.converting_constructors.get(target.record.scope, ())):
            return 4
        return None

    def argument_identity(self, stack, arg):
        while arg["type"] == "ParenthesizedExpression":
            arg = arg["expression"]
        if arg["type"] == "NameExpression":
            name = arg["name"]
            binding = self.lookup_binding(stack, name.removeprefix("::").split("::"), name.startswith("::"))
            if isinstance(binding, DeclaredObject):
                return binding.declared_type
        if arg["type"] == "CallExpression":
            callee = arg["callee"]
            function = self.receiver_binding(stack, callee)
            return self.call_result_binding(stack, function, arg["arguments"], explicit_args="arguments" in callee, type_only=True)
        if arg["type"] in ("SubscriptExpression", "UnaryExpression"):
            op = "*" if arg["type"] == "SubscriptExpression" else arg["operator"]
            if op in ("&", "*"):
                base = self.argument_identity(stack, arg.get("base", arg.get("operand")))
                if base:
                    layers = base.layers[:-1] if base.layers and base.layers[-1].operator in ("&", "&&") else base.layers
                    if op == "&":
                        return base._replace(layers=(*layers, AliasLayer("*")))
                    if layers and layers[-1].operator in ("*", "[]"):
                        return base._replace(layers=layers[:-1])
        if arg["type"] == "TypeConstruction":
            return self.type_argument_identity(stack, {"type": "Type", "specifiers": [arg["target"]], "indirections": []})
        if arg["type"] == "CastExpression":
            return self.type_argument_identity(stack, arg["target"])
        if arg["type"] == "Literal" and "userDefined" not in arg:
            floating = floating_literal_type(arg["raw"])
            if floating:
                return AliasIdentity(floating, frozenset(), ())
        value = self.integral_expression(stack, arg)
        return AliasIdentity(value.words, frozenset(), ()) if isinstance(value, IntegralArgument) and value.words else None

    def derives_from(self, derived, base):
        pending = list(self.base_scopes.get(derived, ()))
        visited = set()
        while pending:
            scope = pending.pop()
            if scope == base:
                return True
            if scope not in visited:
                visited.add(scope)
                pending.extend(self.base_scopes.get(scope, ()))
        return False

    def conditional_receiver(self, stack, expr):
        if self.receiver_binding(stack, expr["test"]) == "dependent_value":
            return "dependent_value"
        arms = []
        for arm in (expr["then"], expr["else"]):
            while arm["type"] == "ParenthesizedExpression":
                arm = arm["expression"]
            arms.append(arm)
        left, right = (self.receiver_binding(stack, arm) for arm in arms)
        if left == right:
            return left
        for binding, other, arm in ((left, right, arms[1]), (right, left, arms[0])):
            if arm["type"] == "ThrowExpression":
                return binding
            if not isinstance(binding, tuple) or binding[0] not in {"closure", "object"} or not binding[2]:
                continue
            # Array-to-pointer conversion can give the two operands a common pointer type.
            pointer = (binding[0], binding[1], ("pointer", *binding[2][1:]))
            if other == pointer or other == "nullptr_t" or (arm["type"] == "Literal" and is_integer_zero_literal(arm["raw"])):
                return pointer
        if (isinstance(left, tuple) and isinstance(right, tuple) and left[0] == right[0] == "object"
                and len(left[2]) == len(right[2]) <= 1):
            layers = ("pointer",) if left[2] else ()
            if self.derives_from(left[1], right[1]):
                return ("object", right[1], layers)
            if self.derives_from(right[1], left[1]):
                return ("object", left[1], layers)
        return None

    def operator_operand_matches(self, expected, actual):
        if expected == actual or not isinstance(expected, tuple):
            return True
        if expected[0] == "closure":
            return False
        return (isinstance(actual, tuple) and expected[0] == actual[0] == "object" and expected[2] == actual[2]
                and self.derives_from(actual[1], expected[1]))

    def binary_receiver(self, stack, expr):
        left = self.receiver_binding(stack, expr["left"])
        right = self.receiver_binding(stack, expr["right"])
        if "dependent_value" in (left, right):
            return "dependent_value"
        comma = expr["type"] == "CommaExpression"
        op = "," if comma else expr["operator"]
        if expr["type"] == "BinaryExpression" and op in {"+", "-"}:
            # An array decays before arithmetic. Subtracting two pointers yields an integer.
            lhs_pointer = isinstance(left, tuple) and left[0] in {"object", "closure"} and bool(left[2])
            rhs_pointer = isinstance(right, tuple) and right[0] in {"object", "closure"} and bool(right[2])
            fallback = None
            if lhs_pointer != rhs_pointer and (lhs_pointer or op == "+"):
                pointer = left if lhs_pointer else right
                fallback = (pointer[0], pointer[1], ("pointer", *pointer[2][1:]))
        elif expr["type"] == "BinaryExpression":
            fallback = None
        else:
            fallback = right if comma else left
        if "void" in (left, right):
            return fallback if comma else None
        return self.operator_receiver(stack, op, (left, right), fallback, (expr["left"], expr["right"]))

    def associated_record_scopes(self, stack, expr):
        pending = [self.argument_identity(stack, expr)]
        classes = []
        while pending:
            item = pending.pop()
            if isinstance(item, AliasIdentity):
                if item.record:
                    classes.append(item.record.scope)
                    pending.extend(item.record.arguments or ())
                for layer in item.layers:
                    pending.extend(layer.parameters)
                    if layer.member_of:
                        classes.append(layer.member_of)
        seen = set()
        while classes:
            scope = classes.pop()
            if scope not in seen:
                seen.add(scope)
                yield scope
                classes.extend(self.base_scopes.get(scope, ()))
                if scope[:-1] in self.class_scopes:
                    classes.append(scope[:-1])

    def operator_receiver(self, stack, op, actual, fallback, expressions=()):
        objects = {b for b in actual if isinstance(b, tuple) and b[0] in {"closure", "object"} and not b[2]}
        if not objects:
            return fallback
        name = "operator" + op
        candidates = set()
        if op != "=":
            candidates.add((False, self.lookup_binding(stack, [name], False)))
            for expr in expressions:
                for record in self.associated_record_scopes(stack, expr):
                    candidates.add((False, self.member_binding(record, name, raw=True)))
                    ns = record[:-1]
                    while ns in self.class_scopes:
                        ns = ns[:-1]
                    for child in self.inline_namespace_set(ns):
                        candidates.add((False, self.bindings.get((*child, name))))
        for obj in objects:
            if obj[0] == "closure":
                continue
            member = self.member_binding(obj[1], name, raw=True)
            if obj == actual[0]:
                candidates.add((True, member))
            if op != "=":
                candidates.add((False, member))  # Hidden friend.
                scope = obj[1][:-1]
                while scope in self.class_scopes:
                    scope = scope[:-1]
                candidates.add((False, self.bindings.get((*scope, name))))
        types = [self.argument_identity(stack, expr) for expr in expressions]
        ranked = []
        for as_member, function in candidates:
            for is_member, formal, result, identities in getattr(function, "operator_overloads", ()):
                if as_member != is_member or len(formal) != len(actual):
                    continue
                if op == "=" and actual[0] == actual[1] and formal != actual:
                    continue
                ranks = []
                for i, (expected, supplied) in enumerate(zip(formal, actual)):
                    if i < len(types) and types[i] is not None and identities[i] is not None:
                        rank = self.conversion_rank(types[i], identities[i], expressions[i])
                    else:
                        rank = 0 if self.operator_operand_matches(expected, supplied) else None
                    if rank is None:
                        break
                    ranks.append(rank)
                else:
                    ranked.append((self.resolved_return(result, None, False), ranks))
        if ranked:
            return self.best_receiver(ranked)
        return fallback

    def qualified_member_key(self, stack, expr):
        if expr["type"] == "NameExpression" and "::" in expr["name"]:
            qualifier, name = expr["name"].rsplit("::", 1)
            scope = self.namespace_path(stack, qualifier) if qualifier else ()
        elif expr["type"] == "QualifiedMemberExpression":
            owner, path = expr["owner"], []
            while owner["type"] == "QualifiedMemberExpression":
                path.append(owner["name"])
                owner = owner["owner"]
            scope = self.base_scope(stack, owner)
            if scope is None:
                return None
            scope, name = (*scope, *reversed(path)), expr["name"]
        else:
            return None
        return self.member_key(scope, name)

    def unary_receiver(self, stack, expr):
        op = expr["operator"]
        if op == "&":
            key = self.qualified_member_key(stack, expr["operand"])
            if key in self.nonstatic_members:
                member = self.bindings[key]
                if isinstance(member, DeclaredObject) and member.receiver:
                    member = member.receiver
                return ("member_pointer", (key[:-1], member), ())
        operand = self.receiver_binding(stack, expr["operand"])
        if op == "&" and isinstance(operand, FunctionBinding):
            return ("function_type", operand, ("pointer",))
        if operand == "dependent_value":
            return operand
        fallback = None
        if isinstance(operand, tuple) and operand[0] in _INDIRECT_BINDINGS:
            kind, owner, layers = operand
            if op == "&":
                fallback = (kind, owner, ("pointer", *layers))
            elif op == "*" and layers:
                fallback = (kind, owner, layers[1:])
            elif op in {"++", "--", "+"} and layers:
                fallback = (kind, owner, ("pointer", *layers[1:]))
        actual = (operand,) if expr["prefix"] else (operand, "value")
        return self.operator_receiver(stack, op, actual, fallback, (expr["operand"],))

    def receiver_binding(self, stack, expr):
        if expr["type"] == "BinaryExpression" and expr["operator"] in {".*", "->*"}:
            obj = self.receiver_binding(stack, expr["left"])
            pointer = self.receiver_binding(stack, expr["right"])
            if expr["operator"] == "->*" and isinstance(obj, tuple) and obj[0] == "object" and not obj[2]:
                return self.operator_receiver(stack, "->*", (obj, pointer), None, (expr["left"], expr["right"]))
            if (isinstance(obj, tuple) and obj[0] == "object"
                    and len(obj[2]) == (expr["operator"] == "->*")
                    and isinstance(pointer, tuple) and pointer[0] == "member_pointer" and not pointer[2]):
                owner, result = pointer[1]
                if obj[1] == owner or self.derives_from(obj[1], owner):
                    return result
            return None
        if expr["type"] == "UnaryExpression" and expr["operator"] in {"++", "--", "*", "&", "+", "-", "!", "~"}:
            return self.unary_receiver(stack, expr)
        if (expr["type"] in {"CommaExpression", "AssignmentExpression"}
                or expr["type"] == "BinaryExpression" and expr["operator"] in _BINARY_VALUE_OPERATORS):
            return self.binary_receiver(stack, expr)
        if expr["type"] == "Literal" and expr["raw"] == "nullptr":
            return "nullptr_t"
        if expr["type"] == "ConditionalExpression":
            return self.conditional_receiver(stack, expr)
        if expr["type"] == "NewExpression":
            element = self.object_binding(stack, expr["allocatedType"])
            if isinstance(element, tuple) and element[0] in {"closure", "object"}:
                layers = tuple(self.receiver_array(stack, size) for size in expr["dimensions"]) + element[2]
                # Array allocation returns a pointer to the first element.
                if layers and isinstance(layers[0], ReceiverArray):
                    layers = layers[1:]
                return (element[0], element[1], ("pointer", *layers))
            return None
        if expr["type"] == "CastExpression":
            return self.object_binding(stack, expr["target"])
        if expr["type"] == "TypeConstruction":
            target = {"type": "Type", "specifiers": [expr["target"]], "indirections": []}
            return self.object_binding(stack, target)
        if expr["type"] == "LambdaExpression":
            generic = bool(expr["templateParameters"]) or self.has_placeholder_parameter(expr["parameters"])
            entry = self.lambda_types.get(id(expr))
            return ("closure", entry[1] if entry else generic, ())
        if expr["type"] in {"NameExpression", "TemplateId"}:
            name = expr["name"]
            binding = self.lookup_binding(stack, name.removeprefix("::").split("::"), name.startswith("::"))
            return (binding.receiver or "value") if isinstance(binding, DeclaredObject) else binding
        if expr["type"] == "QualifiedMemberExpression":
            member = self.bindings.get(self.qualified_member_key(stack, expr))
            return member.receiver if isinstance(member, DeclaredObject) and member.receiver else member
        if expr["type"] == "CallExpression":
            callee = expr["callee"]
            explicit_args = callee["type"] == "TemplateId" or (callee["type"] == "MemberExpression" and "arguments" in callee)
            return self.call_result_binding(stack, self.receiver_binding(stack, callee), expr["arguments"], explicit_args=explicit_args)
        if expr["type"] == "SubscriptExpression":
            binding = self.receiver_binding(stack, expr["base"])
            if isinstance(binding, tuple) and binding[0] == "object" and not binding[2]:
                operator = self.member_binding(binding[1], "operator[]", raw=True)
                return self.call_result_binding(stack, operator, [expr["index"]])
            if not isinstance(binding, tuple) or binding[0] not in _INDIRECT_BINDINGS:
                binding = self.receiver_binding(stack, expr["index"])
            if isinstance(binding, tuple) and binding[0] in _INDIRECT_BINDINGS and binding[2]:
                return (binding[0], binding[1], binding[2][1:])
            return None
        if expr["type"] == "ThisExpression":
            scope = self.namespace([*self.inherited_stack, *stack])
            return ("object", scope, ("pointer",)) if scope in self.class_scopes else None
        if expr["type"] == "ParenthesizedExpression":
            return self.receiver_binding(stack, expr["expression"])
        if expr["type"] == "MemberExpression":
            obj = self.receiver_binding(stack, expr["base"])
            if isinstance(obj, tuple) and obj[0] == "object":
                name, scope = expr["member"], obj[1]
                if owner := expr.get("qualifier"):
                    scope = (self.specialization_scope(stack, owner) if "arguments" in owner
                             else self.namespace_path(stack, owner["name"]))
                elif "::" in name:
                    qualifier, name = name.rsplit("::", 1)
                    scope = self.namespace_path(stack, qualifier)
                return self.member_binding(scope, name, raw=True)
        return None

    def p_namespace_alias(self, p):
        """exportable : namespace_alias_head ';'
           statement : namespace_alias_head ';'"""
        p[0] = p[1]

    def inline_namespace_set(self, scope):
        pending = [scope]
        while pending:
            parent = pending.pop()
            yield parent
            pending.extend(self.inline_children.get(parent, ()))

    def direct_namespace_names(self, scope, name):
        candidates = set()
        for parent in self.inline_namespace_set(scope):
            key = (*parent, name)
            if key in self.namespaces:
                candidates.add(key)
            if key in self.namespace_aliases:
                candidates.add(self.namespace_aliases[key])
            candidates.update(self.injected_namespaces.get(key, ()))
        return candidates

    def qualified_namespace_names(self, scope, name):
        pending, seen, found = [scope], set(), set()
        while pending:
            parent = pending.pop()
            if parent in seen:
                continue
            seen.add(parent)
            direct = self.direct_namespace_names(parent, name)
            if direct:
                found.update(direct)
            else:
                for child in self.inline_namespace_set(parent):
                    pending.extend(self.using_namespaces.get(child, ()))
        return found

    def resolve_namespace_name(self, stack, spelling, name_symbol):
        """Namespace-only lookup for an alias target or a using-directive."""
        absolute = spelling.startswith("::")
        first, *remaining = spelling.removeprefix("::").split("::")
        if absolute:
            found = self.qualified_namespace_names((), first)
        else:
            context = [*self.inherited_stack, *stack]
            scope = self.namespace(context)
            found, active = set(), set()
            for symbol in reversed(context):
                if getattr(symbol, "locals", {}).get(first) == "namespace":
                    found.add(symbol.qualifier_aliases[first])
                    break
                active.update(getattr(symbol, "using_namespaces", ()))
            if not found:
                for parent, nominated in self.nominated_levels(scope, active):
                    found = self.direct_namespace_names(parent, first)
                    for ns in nominated:
                        found.update(self.direct_namespace_names(ns, first))
                    if found:
                        break
        offsets = getattr(name_symbol, "component_offsets", (name_symbol.identifier_offset,))
        offset = offsets[0]
        for part, next_offset in zip(remaining, offsets[1:]):
            if len(found) != 1:
                break
            offset = next_offset
            found = self.qualified_namespace_names(next(iter(found)), part)
        if len(found) > 1:
            raise self.source.error(offset, f"ambiguous namespace name {spelling!r}")
        if not found:
            raise self.source.error(offset, "expected a previously declared namespace")
        return found.pop()

    def p_namespace_alias_head(self, p):
        "namespace_alias_head : NAMESPACE IDENT '=' qualified_name"
        target = self.resolve_namespace_name(p.stack, p[4], p.slice[4])
        scope = next((s for s in reversed(p.stack) if hasattr(s, "locals") or hasattr(s, "namespace")), None)
        if scope is not None and hasattr(scope, "locals"):
            if p[2] in scope.locals and (scope.locals[p[2]] != "namespace" or scope.qualifier_aliases[p[2]] != target):
                raise self.source.error(p.lexpos(2), "conflicting namespace alias")
            scope.locals[p[2]] = "namespace"
            if not hasattr(scope, "qualifier_aliases"):
                scope.qualifier_aliases = {}
            scope.qualifier_aliases[p[2]] = target
        else:
            key = (*self.namespace(p.stack), p[2])
            if key in self.namespaces or (key in self.bindings and key not in self.injected_only) or self.namespace_aliases.get(key, target) != target:
                raise self.source.error(p.lexpos(2), "conflicting namespace alias")
            self.namespace_aliases[key] = target
        p[0] = {"type": "NamespaceAlias", "name": p[2], "target": p[4]}

    def p_using_decl(self, p):
        "using_decl : using_head ';'"
        p[0] = p[1]

    def p_using_head(self, p):
        """using_head : USING NAMESPACE qualified_name
                      | USING ENUM qualified_name
                      | USING using_declarators"""
        name = p[len(p)-1]
        if p.slice[2].type == "NAMESPACE":
            scope = self.resolve_namespace_name(p.stack, name, p.slice[3])
            for symbol in reversed(p.stack):
                if hasattr(symbol, "locals"):
                    symbol.using_namespaces.append(scope)
                    break
                if hasattr(symbol, "namespace"):
                    self.using_namespaces.setdefault(symbol.namespace, []).append(scope)
                    break
            else:
                self.using_namespaces.setdefault((), []).append(scope)
            kind = "UsingDirective"
        elif p.slice[2].type == "ENUM":
            target = self.lookup(p.stack, name.removeprefix("::").split("::"), name.startswith("::"), enum_target=True)
            if target:
                records, key = target
                enum = records.get(key)
                if enum is None or enum["enumerators"] is None:
                    raise self.source.error(p.lexpos(3), "using enum requires a defined enum")
                for item in enum["enumerators"]:
                    self.bind(p.stack, item["name"], self.enumerator_binding(target, item["name"]))
            kind = "UsingEnumDeclaration"
        else:
            p[0] = name[0] if len(name) == 1 else {"type": "UsingDeclarationGroup", "declarations": name}
            return
        p[0] = {"type": kind, "target": name}

    def p_using_declarators(self, p):
        """using_declarators : using_item
                             | using_declarators ',' using_item"""
        p[0] = [p[1]] if len(p) == 2 else [*p[1], p[3]]

    def p_using_item(self, p):
        """using_item : using_declarator
                      | using_declarator ELLIPSIS"""
        p[0] = {**p[1], "pack": True} if len(p) == 3 else p[1]

    def p_using_operator_owner(self, p):
        """using_operator_owner : qualified_name SCOPE
                                | template_owner"""
        p[0] = p[1]

    def p_using_operator(self, p):
        """using_declarator : using_operator_owner operator_id
                            | using_operator_owner OPERATOR type"""
        owner = p[1]["spelling"] if isinstance(p[1], dict) else p[1]
        if len(p) == 3:
            p[0] = {"type": "UsingDeclaration", "target": owner + "::" + p[2], "name": p[2]}
        else:
            target = self.source.spelling(p.lexpos(2), p.lexspan(3)[1]).strip()
            p[0] = {"type": "UsingDeclaration", "target": owner + "::" + target, "conversionType": p[3]}
        if isinstance(p[1], dict):
            p[0]["owner"] = p[1]

    def p_using_declarator(self, p):
        """using_declarator : qualified_name
                            | TYPENAME qualified_name
                            | template_owner IDENT
                            | TYPENAME template_owner IDENT"""
        typename = p.slice[1].type == "TYPENAME"
        if p.slice[-1].type == "qualified_name":
            target = p[len(p)-1]
            parts = target.removeprefix("::").split("::")
            if len(parts) == 1 and not target.startswith("::"):
                raise self.source.error(p.lexpos(len(p)-1), "using declaration requires a qualified name")
            binding = self.lookup_binding(p.stack, parts, target.startswith("::"))
            enum_tag = self.lookup(p.stack, parts, target.startswith("::"), enum_tag=True) == "enum"
            enum_target = self.lookup(p.stack, parts, target.startswith("::"), enum_target=True)
            name = parts[-1]
            node = {"type": "UsingDeclaration", "target": target}
        else:
            owner, name = p[len(p)-2], p[len(p)-1]
            scope = self.specialization_scope(p.stack, owner)
            binding = self.bindings.get((*scope, name))
            enum_tag = (*scope, name) in self.enum_tags
            enum_target = self.enum_targets.get((*scope, name))
            node = {"type": "UsingDeclaration", "target": owner["spelling"] + "::" + name, "owner": owner, "name": name}
        if binding and self.binding_kind(binding) not in ("function", "function_template"):
            home = next((sym for sym in reversed(p.stack) if hasattr(sym, "locals") or hasattr(sym, "namespace")), None)
            if not hasattr(home, "locals"):
                if p.slice[-1].type == "qualified_name":
                    prefix = target.rsplit("::", 1)[0]
                    scope = self.namespace_path(p.stack, prefix) if prefix else ()
                origin = self.expand_namespace((*scope, name))
                key = (*self.namespace(p.stack), name)
                if origin != key and origin in self.bindings:
                    self.using_origins[key] = origin
        if typename:
            node["typename"] = True
            if self.binding_kind(binding) != "type":
                binding = "type"
        if binding:
            self.bind(p.stack, name, binding, enum_tag=enum_tag, enum_target=enum_target)
        p[0] = node

    def p_namespace(self, p):
        """exportable : namespace_head '{' declarations '}'
                      | namespace_head gnu_attribute '{' declarations '}'"""
        if not p[1] and any(sym.type == "EXPORT" for sym in p.stack):
            raise self.source.error(p.lexpos(len(p)-3), "unnamed namespace cannot be exported")
        p[0] = {"type": "NamespaceDefinition", "path": p[1], "declarations": p[len(p)-2]}
        if getattr(p.slice[1], "unnamed_inline", False):
            p[0]["inline"] = True
        if hasattr(p.slice[1], "attributes"):
            p[0]["attributes"] = p.slice[1].attributes
        if len(p) == 6:
            p[0]["gnuAttributes"] = [p[2]]

    def p_namespace_head(self, p):
        """namespace_head : NAMESPACE
                          | NAMESPACE namespace_path
                          | INLINE NAMESPACE
                          | INLINE NAMESPACE attribute_sequence
                          | INLINE NAMESPACE IDENT
                          | NAMESPACE attribute_sequence
                          | NAMESPACE attribute_sequence IDENT
                          | INLINE NAMESPACE attribute_sequence IDENT"""
        inline = p.slice[1].type == "INLINE"
        parts = []
        for sym in p.slice[1:]:
            if sym.type == "attribute_sequence":
                p.slice[0].attributes = sym.value
            elif sym.type == "namespace_path":
                parts = sym.value
            elif sym.type == "IDENT":
                parts = [{"name": sym.value, "inline": inline}]
        enclosing = self.namespace(p.stack)
        if not parts:
            parent = enclosing
            enclosing = (*parent, _UNNAMED_NAMESPACE)
            if parent not in self.unnamed_namespaces:
                self.unnamed_namespaces[parent] = enclosing
                self.using_namespaces.setdefault(parent, []).append(enclosing)
            if inline:
                if enclosing in self.namespaces and enclosing not in self.inline_namespaces:
                    raise self.source.error(p.lexpos(2), "non-inline namespace cannot be reopened as inline")
                self.inline_namespaces.add(enclosing)
                self.inline_children.setdefault(parent, set()).add(enclosing)
            self.namespaces.add(enclosing)
            p.slice[0].unnamed_inline = inline
        offsets = getattr(p.slice[-1], "part_offsets", [p.lexpos(len(p)-1)])
        for part, offset in zip(parts, offsets):
            parent = enclosing
            enclosing = (*parent, part["name"])
            if enclosing in self.namespace_aliases:
                raise self.source.error(offset, "namespace alias cannot be reopened as a namespace")
            for visible in self.visible_namespace_paths(parent):
                if visible != parent:
                    self.injected_namespaces.setdefault((*visible, part["name"]), set()).add(enclosing)
            if part["inline"]:
                if enclosing in self.namespaces and enclosing not in self.inline_namespaces:
                    raise self.source.error(offset, "non-inline namespace cannot be reopened as inline")
                self.inline_namespaces.add(enclosing)
                self.inline_children.setdefault(parent, set()).add(enclosing)
            self.namespaces.add(enclosing)
        p.slice[0].namespace = enclosing
        p[0] = parts

    def p_namespace_path(self, p):
        """namespace_path : IDENT
                          | namespace_path SCOPE IDENT
                          | namespace_path SCOPE INLINE IDENT"""
        part = {"name": p[len(p)-1], "inline": len(p) == 5}
        offsets = [] if len(p) == 2 else p.slice[1].part_offsets
        offsets.append(p.lexpos(len(p)-1))
        p.slice[0].part_offsets = offsets
        if len(p) == 2:
            p[0] = [part]
        else:
            p[1].append(part)
            p[0] = p[1]

    def p_qualified_name(self, p):
        """qualified_name : IDENT %prec END_NAME
                          | SCOPE IDENT
                          | qualified_name SCOPE IDENT"""
        p[0] = p[1] if len(p) == 2 else "::" + p[2] if len(p) == 3 else p[1] + "::" + p[3]
        p.slice[0].identifier_offset = p.lexpos(len(p)-1)
        if len(p) == 4:
            offsets = getattr(p.slice[1], "component_offsets", None)
            if offsets is None:
                offsets = [p.slice[1].identifier_offset]
            offsets.append(p.slice[0].identifier_offset)
            p.slice[0].component_offsets = offsets


    def p_alias(self, p):
        "alias_decl : alias_head ';'"
        p[0] = p[1]

    def p_gnu_alias_attribute(self, p):
        "alias_head : alias_head gnu_attribute"
        p[0] = p[1]
        target = p[0]["declarations"][-1] if p[0]["type"] == "DeclarationGroup" else p[0]
        target["gnuAttributes"] = [*target.get("gnuAttributes", []), p[2]]

    def p_alias_head(self, p):
        """alias_head : USING IDENT '=' abstract_type
                      | USING IDENT attribute_sequence '=' abstract_type
                      | USING IDENT gnu_attribute '=' abstract_type
                      | TYPEDEF type direct_named
                      | TYPEDEF enum_type direct_named
                      | USING IDENT '=' inline_type_id
                      | USING IDENT attribute_sequence '=' inline_type_id
                      | USING IDENT gnu_attribute '=' inline_type_id"""
        if p.slice[1].type == "USING":
            name, target = p[2], p[len(p)-1]
            if p.slice[-1].type == "inline_type_id":
                self.require_type_specifiers(target, p.lexpos(len(p)-1), "alias type")
        else:
            name, base, operators = self.declared_type(p[2], p[3])
            target = self.derived_type(base, operators)
        self.bind_alias(p.stack, name, target)
        p[0] = {"type": "AliasDeclaration", "name": name, "target": target, "syntax": p[1]}
        if p.slice[1].type == "USING" and len(p) == 6:
            if p.slice[3].type == "gnu_attribute":
                p[0]["gnuAttributes"] = [p[3]]
            else:
                p[0]["attributes"] = p[3]

    def bind_record_typedef(self, stack, name, scope, operators):
        layers = self.receiver_layers(stack, operators)
        binding = "type"
        if layers is not None:
            cv = []
            for symbol in reversed(stack):
                if symbol.type == "TYPEDEF":
                    break
                if symbol.type == "modifiers":
                    cv.extend(symbol.value)
            identity = self.apply_alias_declarator(stack, {"declarator": operators},
                                                   AliasIdentity((), frozenset(cv), (), RecordIdentity(scope)))
            binding = ReceiverType(("object", scope, layers), identity)
        self.bind(stack, name, binding, class_target=None if operators else scope)

    def bind_alias(self, stack, name, target):
        obj = self.object_binding(stack, target)
        class_target = enum_target = None
        specs = [s for s in target["specifiers"] if s not in ("const", "volatile")]
        if not target.get("indirections") and not target.get("declarator") and len(specs) == 1:
            spec = specs[0]
            if isinstance(spec, dict) and spec["type"] == "EnumDeclaration":
                # An anonymous enum still has a distinct set of enumerators.
                enum_target = ({name: spec}, name)
            elif isinstance(spec, dict) and spec["type"] == "ClassDeclaration":
                class_target = obj[1]
            elif isinstance(spec, dict) and spec["type"] in {"TypeName", "ElaboratedType"}:
                path = self.specialization_scope(stack, spec) if "arguments" in spec else self.namespace_path(stack, spec["name"])
                if path in self.class_scopes:
                    class_target = path
                elif "arguments" not in spec:
                    spelling = spec["name"]
                    enum_target = self.lookup(stack, spelling.removeprefix("::").split("::"), spelling.startswith("::"),
                                              enum_target=True)
        if isinstance(obj, tuple) and obj[0] in _INDIRECT_BINDINGS:
            record = obj[1] if obj[0] == "object" else None
            binding = ReceiverType(obj, self.alias_identity(stack, target, record_scope=record))
        else:
            binding = self.alias_identity(stack, target) or "type"
        self.bind(stack, name, binding, class_target=class_target, enum_target=enum_target)

    def p_following_typedef(self, p):
        "alias_head : alias_head ',' nested_named"
        if p[1]["type"] == "DeclarationGroup":
            declarations = p[1]["declarations"]
        elif p[1].get("syntax") == "typedef":
            declarations = [p[1]]
        else:
            raise self.source.error(p.lexpos(2), "using-alias requires one declarator")
        specs = declarations[0]["target"]["specifiers"]
        name, operators = p[3]
        target = self.derived_type({"type": "Type", "specifiers": specs, "indirections": []}, operators)
        self.bind_alias(p.stack, name, target)
        declarations.append({"type": "AliasDeclaration", "name": name, "target": target, "syntax": "typedef"})
        p[0] = {"type": "DeclarationGroup", "specifiers": ["typedef", *specs], "declarations": declarations}

    def p_enum_declaration(self, p):
        "enum_decl : enum_definition ';'"
        p[0] = p[1]

    def p_inline_type(self, p):
        """enum_type : enum_specs indirections
           record_type : record_specs indirections"""
        p[0] = {"type": "Type", "specifiers": p[1], "indirections": p[2]}

    def p_inline_specs(self, p):
        # A GNU attribute following the closing brace belongs to the class specifier.
        """enum_specs : enum_definition
                      | modifiers enum_definition
                      | enum_specs modifier
           record_specs : class_specifier %prec END_TYPE
                        | modifiers class_specifier %prec END_TYPE
                        | record_specs modifier"""
        if p.slice[-1].type in {"enum_definition", "class_specifier"}:
            spec = {**p[len(p)-1], "startOffset": p.lexpos(len(p)-1)}
            p[0] = [spec] if len(p) == 2 else [*p[1], spec]
        else:
            p[0] = [*p[1], p[2]]

    def p_enum(self, p):
        """enum_decl : enum_head ';'
           enum_definition : enum_head '{' '}'
                           | enum_head '{' enumerators '}'
                           | enum_head '{' enumerators ',' '}'"""
        head = p[1]
        name = head["name"]
        forward = p.slice[0].type == "enum_decl"
        if not name and (forward or head["scoped"]):
            raise self.source.error(p.lexpos(2), "scoped enum or forward declaration requires a name")
        if forward and "::" in name:
            raise self.source.error(p.slice[1].name_offset, "qualified enum forward declaration")
        if forward and not head["scoped"] and not head["underlying"]:
            raise self.source.error(p.slice[1].name_offset, "unscoped enum declaration requires an underlying type")
        p[0] = {**head, "enumerators": None if forward else [] if len(p) == 4 else p[3]}
        if len(p) == 6:
            p[0]["trailingComma"] = True
        if name:
            records, key = p.slice[1].enum_record
            previous = records.get(key)
            if previous:
                if previous["scoped"] != head["scoped"]:
                    raise self.source.error(p.slice[1].name_offset, "scoped and unscoped enum declarations differ")
                if not head["scoped"] and bool(previous["underlying"]) != bool(head["underlying"]):
                    raise self.source.error(p.slice[1].name_offset, "enum declarations differ in fixed underlying type")
                if not forward and previous["enumerators"] is not None:
                    raise self.source.error(p.slice[1].name_offset, "redefinition of enum")
            if not previous or not forward:
                bindings = {n: ("value" if head["scoped"] else b) for n, b in p.slice[1].locals.items()}
                records[key] = {**p[0], "bindings": bindings}

    def p_enum_key(self, p):
        """enum_key : ENUM
                    | ENUM CLASS
                    | ENUM STRUCT"""
        p[0] = p[2] if len(p) == 3 else "enum"

    def p_enum_prefix(self, p):
        """enum_prefix : enum_key
                       | enum_key attribute_sequence"""
        p[0] = {"type": "EnumDeclaration", "name": None, "scoped": p[1] != "enum", "key": p[1]}
        if len(p) == 3:
            p[0]["attributes"] = p[2]

    def p_enum_named(self, p):
        "enum_named : enum_prefix qualified_name"
        name = p[2]
        parts = name.removeprefix("::").split("::")
        owner = next((s for s in reversed(p.stack) if hasattr(s, "locals") or hasattr(s, "namespace")), None)
        local = owner is not None and hasattr(owner, "locals")
        scope = self.namespace(p.stack)
        if "::" in name:
            prefix = name.rsplit("::", 1)[0]
            enclosing = scope
            scope = self.namespace_path(p.stack, prefix) if prefix else ()
            if local or scope[:len(enclosing)] != enclosing:
                raise self.source.error(p.slice[2].identifier_offset, "enum definition outside its enclosing namespace")
            scope = self.enum_origins.get((*scope, parts[-1]), scope)
            if (*scope, parts[-1]) not in self.enum_records:
                raise self.source.error(p.slice[2].identifier_offset, "qualified enum definition requires a previous declaration")
            p.slice[0].enum_namespace = scope
        if local:
            if not hasattr(owner, "enum_records"):
                owner.enum_records = {}
            p.slice[0].enum_record = owner.enum_records, name
        else:
            for prefix in self.visible_namespace_paths(scope):
                self.enum_origins[(*prefix, parts[-1])] = scope
            p.slice[0].enum_record = self.enum_records, (*scope, parts[-1])
        if "::" not in name:
            self.bind(p.stack, name, "type", enum_tag=True, enum_target=p.slice[0].enum_record)
        p.slice[0].name_offset = p.lexpos(2)
        p[0] = {**p[1], "name": name}

    def p_enum_head(self, p):
        """enum_head : enum_named base_opt
                     | enum_prefix base_opt"""
        p[0] = {**p[1], "underlying": p[2]}
        if p[1]["name"]:
            p.slice[0].enum_record = p.slice[1].enum_record
            p.slice[0].name_offset = p.slice[1].name_offset
        if hasattr(p.slice[1], "enum_namespace"):
            p.slice[0].namespace = p.slice[1].enum_namespace
        p.slice[0].locals = {}

    def p_base_opt(self, p):
        """base_opt : empty
                    | ':' specs"""
        p[0] = None
        if len(p) == 3:
            p[0] = {"type": "Type", "specifiers": p[2], "indirections": []}
            self.require_type_specifiers(p[0], p.lexpos(2), "enum base")

    def p_enumerators(self, p):
        """enumerators : enumerator
                       | enumerators ',' enumerator"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_enumerator(self, p):
        """enumerator : attributed_identifier
                      | attributed_identifier '=' conditional"""
        index = next(i for i in range(len(p.stack)-1, -1, -1) if p.stack[i].type == "enum_head")
        head = p.stack[index]
        if p[1] in head.locals:
            raise self.source.error(p.lexpos(1), "duplicate enumerator")
        if len(p) == 4:
            number = self.array_bound_value(p.stack, p[3])
        else:
            previous = getattr(head, "previous_number", -1)
            number = previous + 1 if previous is not None else None
        head.previous_number = number
        local_binding = ("constant_integer", number) if number is not None else "value"
        binding = "value" if head.value["scoped"] else local_binding
        if head.value["name"]:
            records, key = head.enum_record
            if records is self.enum_records:
                for path in self.visible_namespace_paths(key):
                    self.bindings[(*path, p[1])] = binding
        head.locals[p[1]] = local_binding
        if not head.value["scoped"]:
            if hasattr(head, "namespace"):
                for prefix in self.visible_namespace_paths(head.namespace):
                    self.bindings[(*prefix, p[1])] = binding
            else:
                self.bind(p.stack[:index], p[1], binding)
        p[0] = {"type": "Enumerator", "name": p[1], "value": p[3] if len(p) == 4 else None}
        if attrs := getattr(p.slice[1], "id_attributes", None):
            p[0]["attributes"] = attrs

    def p_instantiation_prefix(self, p):
        """instantiation_prefix : TEMPLATE
                                | EXTERN_TEMPLATE TEMPLATE"""
        p[0] = len(p) == 3

    def p_instantiation_key(self, p):
        """instantiation_key : CLASS
                             | STRUCT
                             | UNION"""
        p[0] = p[1]

    def p_explicit_instantiation(self, p):
        "exportable : instantiation_prefix instantiation_key qualified_name ANGLE_OPEN template_arguments_opt ANGLE_CLOSE ';'"
        name = p[3]
        if (self.lookup(p.stack, name.removeprefix("::").split("::"), name.startswith("::")) != "type_template"
                or self.namespace_path(p.stack, name) not in self.class_scopes):
            raise self.source.error(p.lexpos(3), "expected a class template for explicit instantiation")
        p[0] = {"type": "ExplicitInstantiation", "extern": p[1], "key": p[2],
                "target": {"type": "TypeName", "name": name, "arguments": p[5]}}

    def p_instantiated_declarator(self, p):
        """exportable : instantiation_prefix declared_head ';'
                      | instantiation_prefix special_head ';'"""
        p[0] = {"type": "ExplicitInstantiation", "extern": p[1], "declaration": p[2]}

    def p_explicit_header(self, p):
        "explicit_header : TEMPLATE ANGLE_OPEN ANGLE_CLOSE"

    def p_explicit_specialization(self, p):
        """template_decl : explicit_header class_decl
                         | explicit_header variable
                         | explicit_header function
                         | explicit_header special_function"""
        if "specialization" not in p[2] and "owner" not in p[2] and p[2]["type"] != "FunctionDeclaration":
            raise self.source.error(p.lexpos(2), "explicit specialization requires a template-id")
        p[0] = {"type": "ExplicitSpecialization", "declaration": p[2]}

    def p_gnu_extension_declaration(self, p):
        "typed_declaration : GNU_EXTENSION typed_declaration"
        p[0] = {"type": "GnuExtensionDeclaration", "declaration": p[2]}

    def p_template_decl(self, p):
        """template_decl : TEMPLATE ANGLE_OPEN template_parameters ANGLE_CLOSE requires_opt typed_declaration
                         | TEMPLATE ANGLE_OPEN template_parameters ANGLE_CLOSE concept_definition"""
        decl = p[len(p)-1]
        if decl["type"] == "FunctionDeclaration" and "owner" not in decl:
            self.bind(p.stack, decl["name"], "function_template")
        elif decl["type"] == "VariableDeclaration" and "owner" not in decl and "specialization" not in decl:
            self.bind(p.stack, decl["name"], "variable_template")
        elif decl["type"] in {"ClassDeclaration", "AliasDeclaration"} and "specialization" not in decl and "owner" not in decl:
            self.bind(p.stack, decl["name"], "type_template")
        p[0] = {"type": "TemplateDeclaration", "parameters": p[3], "declaration": decl}
        if len(p) == 7 and p[5] is not None:
            p[0]["requires"] = p[5]

    def p_template_parameters(self, p):
        """template_parameters : template_parameter
                               | template_parameters ',' template_parameter"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_template_parameter(self, p):
        """template_parameter : TYPENAME IDENT
                              | CLASS IDENT
                              | TYPENAME
                              | CLASS
                              | TYPENAME IDENT '=' abstract_type
                              | CLASS IDENT '=' abstract_type
                              | TYPENAME '=' abstract_type
                              | CLASS '=' abstract_type
                              | TYPENAME ELLIPSIS IDENT
                              | CLASS ELLIPSIS IDENT
                              | TYPENAME ELLIPSIS
                              | CLASS ELLIPSIS
                              | type_constraint IDENT
                              | type_constraint ELLIPSIS IDENT
                              | type_constraint IDENT '=' abstract_type"""
        head = next(sym for sym in reversed(p.stack) if sym.type in {"TEMPLATE", "lambda_intro"})
        name = next((sym.value for sym in p.slice[2:] if sym.type == "IDENT"), None)
        pack = any(sym.type == "ELLIPSIS" for sym in p.slice)
        if name:
            head.template_types.add(name)
        if p.slice[1].type == "type_constraint":
            p[0] = {"type": "TypeTemplateParameter", "constraint": p[1], "name": name}
        else:
            p[0] = {"type": "TypeTemplateParameter", "key": p[1], "name": name}
        if pack:
            p[0]["pack"] = True
            if name:
                head.template_packs.add(name)
        if p.slice[-1].type == "abstract_type":
            p[0]["default"] = p[len(p)-1]

    def p_non_type_template_parameter(self, p):
        """template_parameter : abstract_type
                              | abstract_type '=' initializer
                              | type direct_named
                              | type direct_named '=' initializer
                              | type ELLIPSIS
                              | type ungrouped_pack
                              | type grouped_pack"""
        target, name = p[1], None
        pack = p.slice[1].type == "type" and p.slice[2].type in {"ELLIPSIS", "ungrouped_pack", "grouped_pack"}
        if p.slice[1].type == "type" and p.slice[2].type != "ELLIPSIS":
            name, base, operators = self.declared_type(p[1], p[2])
            target = self.derived_type(base, operators)
        p[0] = {"type": "NonTypeTemplateParameter", "parameterType": target, "name": name}
        if name:
            head = next(sym for sym in reversed(p.stack) if sym.type in {"TEMPLATE", "lambda_intro"})
            head.template_values.add(name)
            if pack:
                head.template_packs.add(name)
        if pack:
            p[0]["pack"] = True
        if len(p) > 2 and (attrs := getattr(p.slice[2], "id_attributes", None)):
            p[0]["declaratorAttributes"] = attrs
        if p.slice[-1].type == "initializer":
            p[0]["default"] = p[len(p)-1]

    def p_template_template_parameter(self, p):
        """template_parameter : template_template_head template_key template_pack_opt optional_id template_default_opt"""
        name, pack = p[4], p[3]
        head = next(sym for sym in reversed(p.stack) if sym.type in {"TEMPLATE", "lambda_intro"})
        if name:
            head.template_names.add(name)
            head.template_types.add(name)
            if pack:
                head.template_packs.add(name)
        p[0] = {"type": "TemplateTemplateParameter", "key": p[2], "name": name, "parameters": p[1]}
        if pack:
            p[0]["pack"] = True
        if p[5] is not None:
            if pack:
                raise self.source.error(p.lexpos(5), "template parameter pack cannot have a default")
            p[0]["default"] = p[5]

    def p_template_default_opt(self, p):
        """template_default_opt : empty
                                | '=' qualified_name"""
        p[0] = p[2] if len(p) == 3 else None

    def p_template_template_head(self, p):
        "template_template_head : TEMPLATE ANGLE_OPEN template_parameters ANGLE_CLOSE"
        p[0] = p[3]

    def p_template_key(self, p):
        """template_key : CLASS
                        | TYPENAME"""
        p[0] = p[1]

    def p_template_pack_opt(self, p):
        """template_pack_opt : empty
                             | ELLIPSIS"""
        p[0] = p[1] == "..."

    def p_optional_id(self, p):
        """optional_id : empty
                       | IDENT"""
        p[0] = p[1]

    def p_named_type(self, p):
        """named_type : TYPE_NAME
                      | TYPE_NAME ANGLE_OPEN template_arguments_opt ANGLE_CLOSE"""
        p[0] = {"type": "TypeName", "name": p[1]}
        if getattr(p.slice[1], "implicit_typename", False):
            p[0]["implicitTypename"] = True
        if len(p) == 5:
            p[0]["arguments"] = p[3]

    def p_nested_member_type(self, p):
        """named_type : named_type MEMBER_TYPE_SCOPE IDENT
                      | named_type MEMBER_TYPE_SCOPE IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE
                      | named_type MEMBER_TYPE_SCOPE TEMPLATE IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE"""
        explicit = p.slice[3].type == "TEMPLATE"
        p[0] = {"type": "QualifiedType", "qualifier": p[1], "name": p[4] if explicit else p[3]}
        if len(p) > 4:
            p[0]["arguments"] = p[len(p)-2]
        if explicit:
            p[0]["template"] = True

    def p_integer_sequence_type(self, p):
        "type_transform : MAKE_INTEGER_SEQ ANGLE_OPEN template_argument ',' abstract_type ',' conditional ANGLE_CLOSE"
        if p[3]["type"] not in {"TemplateName", "DependentTemplateName"}:
            raise self.source.error(p.lexpos(3), "integer-sequence builtin requires a template name")
        self.require_type_specifiers(p[5], p.lexpos(5), "integer-sequence element type")
        p[0] = {"type": "BuiltinIntegerSequence", "template": p[3], "elementType": p[5], "length": p[7]}

    def p_pack_element_type(self, p):
        "type_transform : PACK_ELEMENT ANGLE_OPEN conditional ',' trait_types ANGLE_CLOSE"
        p[0] = {"type": "BuiltinPackElement", "index": p[3], "operands": p[5]}

    def p_template_arguments_opt(self, p):
        """template_arguments_opt : empty
                                  | template_arguments"""
        p[0] = p[1] or []

    def p_template_arguments(self, p):
        """template_arguments : template_element
                              | template_arguments ',' template_element"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_template_element(self, p):
        """template_element : template_argument
                            | template_argument ELLIPSIS"""
        p[0] = p[1] if len(p) == 2 else {"type": "PackExpansion", "pattern": p[1]}

    def p_template_argument(self, p):
        """template_argument : abstract_type
                             | conditional
                             | TEMPLATE_NAME"""
        p[0] = {"type": "TemplateName", "name": p[1]} if p.slice[1].type == "TEMPLATE_NAME" else p[1]

    def p_dependent_template_argument(self, p):
        """template_argument : named_type TEMPLATE_MEMBER_SCOPE TEMPLATE IDENT
                             | qualified_name SCOPE TEMPLATE IDENT"""
        owner = p[1] if p.slice[1].type == "named_type" else {"type": "TypeName", "name": p[1]}
        p[0] = {"type": "DependentTemplateName", "owner": owner, "name": p[4]}

    def p_dependent_type(self, p):
        "dependent_type : TYPENAME dependent_path"
        p[0] = {"type": "DependentType", "absolute": p[2][0], "segments": p[2][1]}

    def p_dependent_path(self, p):
        """dependent_path : decltype_spec SCOPE dependent_tail
                          | dependent_segment SCOPE dependent_tail
                          | SCOPE dependent_segment SCOPE dependent_tail
                          | dependent_path DEP_SCOPE dependent_tail"""
        if p.slice[1].type == "dependent_path":
            p[0] = p[1]
            p[0][1].append(p[3])
        elif p.slice[1].type == "decltype_spec":
            p[0] = (False, [{"decltype": p[1]}, p[3]])
        elif p.slice[1].type == "SCOPE":
            p[0] = (True, [p[2], p[4]])
        else:
            p[0] = (False, [p[1], p[3]])

    def p_dependent_segment(self, p):
        """dependent_segment : IDENT
                             | IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE"""
        p[0] = {"name": p[1]}
        if len(p) == 5:
            p[0]["arguments"] = p[3]

    def p_dependent_tail(self, p):
        """dependent_tail : dependent_segment
                          | TEMPLATE IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE"""
        p[0] = p[1] if len(p) == 2 else {"name": p[2], "template": True, "arguments": p[4]}

    def require_type_specifiers(self, target, offset, context, *, allow_constexpr=False):
        declaration_only = {"constexpr", "consteval", "constinit", "static", "extern",
                            "thread_local", "mutable", "inline", "virtual", "friend", "explicit"}
        if allow_constexpr:
            declaration_only.remove("constexpr")
        if any(isinstance(s, str) and s in declaration_only for s in target["specifiers"]):
            raise self.source.error(offset, f"expected type specifiers in {context}")

    def p_type(self, p):
        # A new-type-id consumes the longest sequence of pointer operators.
        "type : specs indirections %prec END_TYPE"
        p[0] = {"type": "Type", "specifiers": p[1], "indirections": p[2]}

    def p_specs(self, p):
        """specs : builtin_specs %prec END_TYPE
                 | named_specs %prec END_TYPE
           builtin_specs : BUILTIN
                         | modifiers BUILTIN
                         | builtin_specs BUILTIN
                         | builtin_specs modifier
           named_specs : named_type
                       | constrained_placeholder
                       | modifiers constrained_placeholder
                       | elaborated_type
                       | modifiers elaborated_type
                       | dependent_type
                       | modifiers dependent_type
                       | type_transform
                       | modifiers type_transform
                       | decltype_spec
                       | modifiers decltype_spec
                       | modifiers named_type
                       | named_specs modifier
           modifiers : modifier
                     | modifiers modifier
                     | modifiers gnu_attribute"""
        if p.slice[0].type == "specs":
            p[0] = p[1]
        else:
            last = p.slice[-1]
            p[0] = [] if len(p) == 2 else p[1]
            if p.slice[1].type == "builtin_specs" and last.type == "BUILTIN":
                words = [w for w in [*p[0], last.value] if isinstance(w, str) and w in BUILTINS]
                words = ["signed" if w in {"__signed", "__signed__"} else w for w in words]
                # Compiler-specific base types have their own specifier combinations.
                if not any(w.startswith("_") for w in words) and tuple(sorted(words)) not in _BUILTIN_COMBINATIONS:
                    raise self.source.error(last.lexpos, f"incompatible type specifiers {' '.join(words)}")
            p[0].append(last.value)

    def p_constrained_placeholder(self, p):
        """constrained_placeholder : type_constraint BUILTIN
                                   | type_constraint decltype_spec"""
        placeholder = p[2]
        if isinstance(placeholder, dict):
            placeholder = "decltype(auto)" if placeholder["operand"] == "auto" else None
        if placeholder not in {"auto", "decltype(auto)"}:
            raise self.source.error(p.lexpos(2), "type constraint requires a placeholder type")
        p[0] = {"type": "ConstrainedPlaceholder", "constraint": p[1], "placeholder": placeholder}

    def p_type_transform(self, p):
        "type_transform : TYPE_TRANSFORM '(' abstract_type ')'"
        self.require_type_specifiers(p[3], p.lexpos(3), "builtin type transform")
        p[0] = {"type": "BuiltinTypeTransform", "name": p[1], "operand": p[3]}

    def p_gnu_typeof(self, p):
        """type_transform : GNU_TYPEOF TYPE_PAREN abstract_type ')'
                          | GNU_TYPEOF '(' expression ')'"""
        p[0] = {"type": "GnuTypeof", "spelling": p[1], "operand": p[3]}

    def p_elaborated_type(self, p):
        """elaborated_type : ELAB_KEY qualified_name %prec END_NAME
                           | ELAB_KEY specialized_class_name"""
        if p.slice[2].type == "specialized_class_name":
            p[0] = {**p[2], "type": "ElaboratedType", "key": p[1]}
            return
        name = p[2]
        parts = name.removeprefix("::").split("::")
        known = self.lookup(p.stack, parts, name.startswith("::"))
        if p[1] == "enum":
            dependent = len(parts) > 1 and not name.startswith("::") and any(
                parts[0] in getattr(sym, "template_types", ()) for sym in [*self.inherited_stack, *p.stack])
            if not dependent and self.lookup(p.stack, parts, name.startswith("::"), enum_tag=True) != "enum":
                raise self.source.error(p.lexpos(2), "expected a previously declared enumeration")
            p[0] = {"type": "ElaboratedType", "key": p[1], "name": name}
            return
        if known is None:
            if len(parts) != 1 or name.startswith("::"):
                raise self.source.error(p.lexpos(2), "unknown qualified class name")
            # First use introduces the tag in the closest block or namespace, even
            # when it occurs inside a member declaration or a parameter clause.
            scope = next((s for s in reversed(p.stack) if s.type in {"BLOCK_OPEN", "namespace_head"}), None)
            if scope is not None and scope.type == "BLOCK_OPEN":
                scope.locals[name] = "type"
            elif not self.inherited_stack:
                ns = scope.namespace if scope is not None else ()
                self.bindings[(*ns, name)] = "type"
                self.class_scopes.add((*ns, name))
        p[0] = {"type": "ElaboratedType", "key": p[1], "name": name}

    def p_decltype_spec(self, p):
        """decltype_spec : DECLTYPE '(' expression ')'
                         | DECLTYPE '(' BUILTIN ')'"""
        if p.slice[3].type == "BUILTIN" and p[3] != "auto":
            raise self.source.error(p.lexpos(3), "decltype requires an expression or auto")
        p[0] = {"type": "Decltype", "operand": p[3]}
        if p[1] == "__decltype":
            p[0]["gnuSpelling"] = p[1]

    def p_modifier(self, p):
        """modifier : SPECIFIER
                    | INLINE
                    | VIRTUAL
                    | FRIEND
                    | EXPLICIT
                    | EXPLICIT EXPLICIT_OPEN conditional ')'"""
        p[0] = p[1] if len(p) == 2 else {"type": "ExplicitSpecifier", "condition": p[3]}

    def p_indirections(self, p):
        """indirections : empty
                        | indirections '*' pointer_qualifiers
                        | indirections MEMBER_POINTER pointer_qualifiers %prec '*'
                        | indirections pointer_template_owner '*' pointer_qualifiers
                        | indirections '&'
                        | indirections '&' attribute_sequence
                        | indirections AND attribute_sequence
                        | indirections '&' GNU_RESTRICT
                        | indirections AND GNU_RESTRICT
                        | indirections AND"""
        if len(p) == 2:
            p[0] = []
            return
        prefix = p.slice[2].type
        op = {"operator": p[2] if prefix in {"&", "AND"} else "*"}
        if prefix == "pointer_template_owner":
            op.update({"class": p[2]["spelling"], "owner": p[2]})
        elif prefix == "MEMBER_POINTER":
            op["class"] = p[2]
        suffix = p.slice[-1]
        if suffix.type == "attribute_sequence":
            self.check_type_attributes(suffix.value, "a reference type")
            op["attributes"] = suffix.value
        elif suffix.type == "GNU_RESTRICT":
            op["qualifiers"] = [suffix.value]
        elif suffix.type == "pointer_qualifiers":
            if suffix.value or "class" in op:
                op["qualifiers"] = suffix.value
            if attrs := getattr(suffix, "pointer_attributes", None):
                op["attributes"] = attrs
            if attrs := getattr(suffix, "gnu_attributes", None):
                op["gnuAttributes"] = attrs
        p[0] = p[1] + [op["operator"] if len(op) == 1 else op]

    def p_pointer_qualifiers(self, p):
        """pointer_qualifiers : %prec END_TYPE
                              | attribute_sequence %prec END_TYPE
                              | pointer_qualifiers SPECIFIER
                              | pointer_qualifiers GNU_RESTRICT
                              | pointer_qualifiers gnu_attribute"""
        if len(p) <= 2:
            p[0] = []
            if len(p) == 2:
                self.check_type_attributes(p[1], "a pointer type")
                p.slice[0].pointer_attributes = p[1]
        else:
            p.slice[0].pointer_attributes = getattr(p.slice[1], "pointer_attributes", None)
            p.slice[0].gnu_attributes = getattr(p.slice[1], "gnu_attributes", [])
            if p.slice[2].type == "gnu_attribute":
                p.slice[0].gnu_attributes.append(p[2])
                p[0] = p[1]
                return
            if p[2] not in {"const", "volatile", "__restrict", "__restrict__"}:
                raise self.source.error(p.lexpos(2), "expected cv qualifier on pointer")
            p[1].append(p[2])
            p[0] = p[1]

    def p_binding_initializer(self, p):
        """binding_initializer : '=' initializer
                        | '(' initializers ')'
                        | braces"""
        if len(p) == 4:
            p[0] = {"type": "DirectInitializer", "arguments": p[2]}
        elif len(p) == 3:
            p[0] = {"type": "CopyInitializer", "value": p[2]}
        else:
            p[0] = p[1]

    def p_binding_names(self, p):
        """binding_names : IDENT
                         | binding_names ',' IDENT"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            if p[3] in p[1]:
                raise self.source.error(p.lexpos(3), "duplicate structured binding")
            p[1].append(p[3])
            p[0] = p[1]

    def p_binding_head(self, p):
        "binding_head : type '[' binding_names ']'"
        target = p[1]
        permitted = ("auto", "const", "volatile", "static", "thread_local")
        if (target["specifiers"].count("auto") != 1 or any(s not in permitted for s in target["specifiers"])
                or target["indirections"] not in ([], ["&"], ["&&"], ["and"], ["bitand"])):
            raise self.source.error(p.lexpos(1), "structured binding requires auto with an optional reference")
        p[0] = {"type": "StructuredBinding", "variableType": target, "names": p[3]}

    def p_binding_variable_head(self, p):
        "binding_variable_head : binding_head"
        for name in p[1]["names"]:
            self.bind(p.stack, name, "value", declaration_offset=p.lexpos(1))
        p[0] = p[1]

    def p_binding_variable(self, p):
        "variable : binding_variable_head binding_initializer ';'"
        p[0] = {**p[1], "initializer": p[2]}

    def p_variable(self, p):
        "variable : init_declarators ';'"
        specs, declarations = p[1]
        p[0] = declarations[0] if len(declarations) == 1 else {
            "type": "DeclarationGroup", "specifiers": specs, "declarations": declarations}

    def p_init_declarators(self, p):
        """init_declarators : declared_head init_clause
                            | following_head init_clause"""
        form, value = p[2]
        node = p[1]
        if node["type"] == "FunctionDeclaration":
            node["body"] = None
            if form == "=" and value == {"type": "Literal", "raw": "0"}:
                node["functionSpecifier"] = "pure"
            elif form in {"default", "delete"}:
                node["functionSpecifier"] = form
            elif form:
                raise self.source.error(p.lexpos(2), "unexpected function initializer")
        else:
            if form in {"default", "delete"}:
                raise self.source.error(p.lexpos(2), "expected function declarator")
            node["initializer"] = value
            self.bind_initialized_array(p.stack, node, value)
            self.bind_constant_initializer(p.stack, node, form, value)
            target = node["variableType"]
            deduced = "auto" in target["specifiers"] or {"type": "Decltype", "operand": "auto"} in target["specifiers"]
            if (deduced and not node["dimensions"] and not target.get("declarator")
                    and not (form == "=" and value and value["type"] == "InitializerList")):
                receiver = self.initializer_receiver(p.stack, value)
                if receiver:
                    if ("auto" in target["specifiers"] and receiver[2] and isinstance(receiver[2][0], ReceiverArray)
                            and not any(op in ("&", "&&") for op in target["indirections"])):
                        receiver = (receiver[0], receiver[1], ("pointer", *receiver[2][1:]))
                    name = node["name"]
                    current = self.lookup_binding(p.stack, name.removeprefix("::").split("::"), name.startswith("::"))
                    self.bind(p.stack, name, current._replace(receiver=receiver) if isinstance(current, DeclaredObject) else receiver)
        declarations = getattr(p.slice[1], "previous_declarations", [])
        declarations.append(node)
        p[0] = (p.slice[1].specifiers, declarations)

    def bind_initialized_array(self, stack, node, initializer):
        if not initializer or initializer["type"] not in ("InitializerList", "DirectInitializer", "StringLiteral", "ParenthesizedExpression"):
            return
        name = node["name"]
        binding = self.lookup_binding(stack, name.removeprefix("::").split("::"), name.startswith("::"))
        if isinstance(binding, DeclaredObject):
            identity = binding.declared_type
            if binding.receiver and not any(layer.operator in ("*", "::*") for layer in identity.layers):
                return
        elif (isinstance(binding, tuple) and binding[0] in ("object", "function_type", "member_pointer")
              and binding[2][:1] == (ReceiverArray(None, omitted=True),)
              and (binding[0] == "member_pointer" or "pointer" in binding[2])):
            identity = self.receiver_layout(binding)
        else:
            return
        if not identity.layers or identity.layers[-1] != AliasLayer("[]", bound=None):
            return
        elements = initializer.get("elements", initializer.get("arguments", []))
        character_array = (isinstance(binding, DeclaredObject) and all(layer.operator == "[]" for layer in identity.layers)
                           and any(w in ("char", "wchar_t", "char8_t", "char16_t", "char32_t") for w in identity.words))
        string = elements[0] if len(elements) == 1 else initializer
        while string["type"] == "ParenthesizedExpression":
            string = string["expression"]
        if string["type"] == "StringLiteral" and character_array and len(identity.layers) == 1:
            if "userDefined" in string:
                return
            count = string_array_extent(string)
        elif initializer["type"] == "DirectInitializer":
            count = len(elements)
        elif initializer["type"] == "InitializerList":
            # Each stride is the scalar capacity of one nested array. A braced
            # clause initializes the current subobject in full, even when empty.
            extents = []
            for layer in reversed(identity.layers[:-1]):
                if layer.operator != "[]":
                    break
                if not layer.bound or layer.bound < 0:
                    return
                extents.append(layer.bound)
            strides = [1]
            for extent in reversed(extents):
                strides.append(strides[-1] * extent)
            strides.reverse()
            capacity = strides[0]
            offset = 0
            for item in elements:
                if item["type"] == "StringLiteral" and character_array and extents and "userDefined" not in item:
                    offset += extents[-1]
                elif item["type"] == "InitializerList":
                    offset += next(step for step in strides if offset % step == 0)
                else:
                    offset += 1
            count = (offset + capacity - 1) // capacity
        else:
            return
        if count:
            outer = AliasLayer("[]", bound=count)
            if isinstance(binding, DeclaredObject):
                receiver = binding.receiver
                if receiver:
                    receiver = (receiver[0], receiver[1], (ReceiverArray(count), *receiver[2][1:]))
                binding = binding._replace(declared_type=identity._replace(layers=(*identity.layers[:-1], outer)), receiver=receiver)
            else:
                binding = (binding[0], binding[1], (ReceiverArray(count), *binding[2][1:]))
            self.bind(stack, name, binding)

    def bind_constant_initializer(self, stack, node, form, value):
        target = node["variableType"]
        specs = target["specifiers"]
        if (value is None or not (any(s in ("constexpr", "const") for s in specs) or "&" in target["indirections"])
                or node["dimensions"]
                or "owner" in node or "specialization" in node):
            return
        words = [s for s in specs if s not in ("constexpr", "const", "static", "inline", "extern")]
        name = node["name"]
        binding = self.lookup_binding(stack, name.removeprefix("::").split("::"), name.startswith("::"))
        if binding != "value" and not isinstance(binding, DeclaredObject):
            return
        if "auto" in words and form == "=" and value["type"] == "InitializerList":
            return
        if value["type"] in ("DirectInitializer", "InitializerList"):
            items = value.get("arguments", value.get("elements"))
            if len(items) != 1:
                return
            value = items[0]
        declared = binding.declared_type if isinstance(binding, DeclaredObject) else None
        if declared is None and "auto" in words:
            declared = self.alias_identity(stack, {**target, "specifiers": ["auto"]})
        if declared is not None and (declared.layers or "auto" in words):
            reference = declared.layers and declared.layers[-1].operator == "&"
            if reference or "constexpr" in specs:
                result = self.value_argument(stack, value, declared)
                if isinstance(result, AddressArgument):
                    actual = result.declared_type if "auto" in words else declared
                    if not reference:
                        # A pointer copied as a value loses its top-level cv qualifiers.
                        if actual.layers:
                            outer = actual.layers[-1]._replace(qualifiers=frozenset())
                            result = result._replace(declared_type=actual._replace(layers=(*actual.layers[:-1], outer)))
                        if "constexpr" in specs:
                            actual = actual.qualified(frozenset({"const"}))
                    stored = binding if isinstance(binding, DeclaredObject) else DeclaredObject(actual)
                    self.bind(stack, name, stored._replace(declared_type=actual, address=result))
                    return
            if declared.layers:
                return
        if not words or not all(s in ("int", "char", "short", "long", "signed", "unsigned", "auto", "bool") for s in words):
            return
        constant = self.integral_expression(stack, value)
        if isinstance(constant, IntegralArgument) and constant.value is not None:
            number = constant.value
            if "auto" in words and constant.words:
                binding = DeclaredObject(AliasIdentity(constant.words, frozenset({"const"}), ()))
        else:
            number = self.array_bound_value(stack, value)
        if number is None:
            return
        if "bool" in words:
            number = int(bool(number))
        elif "auto" not in words:
            bits = 8 if "char" in words else 16 if "short" in words else 64 if "long" in words else 32
            number %= 1 << bits
            if "unsigned" not in words and number >= 1 << (bits - 1):
                number -= 1 << bits
        self.bind(stack, name, binding._replace(constant=number) if isinstance(binding, DeclaredObject)
                  else ("constant_integer", number))

    def p_init_clause(self, p):
        """init_clause : empty
                       | '=' DEFAULT
                       | '=' DELETE
                       | '=' initializer
                       | HEAD_END braces
                       | INIT_OPEN initializers ')'"""
        if len(p) == 2:
            p[0] = (None, None)
        elif p.slice[2].type in {"DEFAULT", "DELETE"}:
            p[0] = (p[2], None)
        elif p.slice[1].type == "INIT_OPEN":
            p[0] = ("()", {"type": "DirectInitializer", "arguments": p[2]})
        else:
            p[0] = (p[1], p[2])

    def p_declared_head(self, p):
        """declared_head : type direct_named trailing_return_opt requires_opt virt_specifiers
                         | type gnu_attribute direct_named trailing_return_opt requires_opt virt_specifiers
                         | enum_type direct_named trailing_return_opt requires_opt virt_specifiers"""
        index = 3 if p.slice[2].type == "gnu_attribute" else 2
        self.attach_trailing_type(p, index, index+1)
        self.finish_head(p, p[1], p[index], p[index+3], p.lexpos(index+3), p.lexpos(index), p.slice[index], p[index+2])
        self.attach_requires(p, index+2)
        if index == 3:
            p[0]["gnuAttributes"] = [p[2]]

    def p_following_head(self, p):
        "following_head : init_declarators ',' nested_named trailing_return_opt requires_opt virt_specifiers"
        specs, declarations = p[1]
        self.attach_trailing_type(p, 3, 4)
        self.finish_head(p, {"specifiers": specs, "indirections": []}, p[3], p[6], p.lexpos(6), p.lexpos(3), p.slice[3], p[5])
        self.attach_requires(p, 5)
        p.slice[0].previous_declarations = declarations

    def attach_requires(self, p, index):
        if p[index] is not None:
            if p[0]["type"] != "FunctionDeclaration" or p[0].get("virtSpecifiers"):
                raise self.source.error(p.lexpos(index), "requires-clause requires a function without virtual specifiers")
            p[0]["requires"] = p[index]

    def finish_head(self, p, base_type, declarator, virt, virt_offset, name_offset, symbol, trailing_requires=None):
        owner = getattr(symbol, "owner", None)
        specialization = getattr(symbol, "specialization", None)
        name, declared_type, operators = self.declared_type(base_type, declarator)
        p.slice[0].specifiers = base_type["specifiers"]
        function = bool(operators and operators[0]["type"] == "FunctionOperator")
        return_type = self.derived_type(declared_type, operators[1:]) if function else None
        if p.stack[-1].type == "instantiation_prefix":
            kind = self.lookup(p.stack, name.removeprefix("::").split("::"), name.startswith("::"))
            expected = "function_template" if operators and operators[0]["type"] == "FunctionOperator" else "variable_template"
            if owner is None and kind != expected:
                raise self.source.error(name_offset, "expected a template for explicit instantiation")
            if owner:
                p.slice[0].namespace = self.specialization_scope(p.stack, owner)
        elif p.stack[-1].type == "explicit_header" and operators and operators[0]["type"] == "FunctionOperator":
            if owner:
                p.slice[0].namespace = self.specialization_scope(p.stack, owner)
            elif self.lookup(p.stack, name.removeprefix("::").split("::"), name.startswith("::")) != "function_template":
                raise self.source.error(name_offset, "expected a function template for explicit specialization")
        elif owner:
            scope = self.specialization_scope(p.stack, owner)
            key = (*scope, name.rsplit("::", 1)[-1])
            # A definition outside the class keeps the template classification
            # established by its member declaration inside the class.
            if function:
                self.store_binding(self.bindings, key, self.function_binding(p.stack, name, "function", operators[0], return_type, symbol))
            elif self.binding_kind(self.bindings.get(key)) != "function_template":
                self.bindings[key] = "value"
            p.slice[0].namespace = scope
        elif specialization:
            friend = "friend" in base_type["specifiers"] and operators and operators[0]["type"] == "FunctionOperator"
            if operators and operators[0]["type"] == "FunctionOperator" and not friend:
                raise self.source.error(name_offset, "variable template cannot specialize a function")
            if not friend and p.stack[-1].type not in {"explicit_header", "requires_opt"}:
                raise self.source.error(name_offset, "variable specialization requires a template header")
        else:
            kind = "function" if function else "value"
            end = len(p.stack)-1
            while end >= 0 and p.stack[end].type in {"attribute_specifier", "gnu_attribute", "GNU_EXTENSION"}:
                end -= 1
            if end >= 4 and p.stack[end].type == "requires_opt" and p.stack[end-4].type == "TEMPLATE":
                kind = "function_template" if function else "variable_template"
            if function:
                if self.has_placeholder_parameter(operators[0]["parameters"]):
                    kind = "function_template"
                header = end >= 4 and p.stack[end-4].type == "TEMPLATE" and p.stack[end].type == "requires_opt"
                params = p.stack[end-2].value if header else None
                requirements = (p.stack[end].value if header else None, trailing_requires)
                kind = self.function_binding(p.stack, name, kind, operators[0], return_type, symbol, params, requirements)
            elif kind == "value":
                target = self.derived_type(declared_type, operators)
                kind = self.declared_binding(p.stack, target)
            scope = next((sym for sym in reversed(p.stack) if hasattr(sym, "locals") or hasattr(sym, "namespace")), None)
            if (getattr(scope, "type", None) == "class_head" and "::" not in name
                    and not any(spec in ("friend", "static") for spec in base_type["specifiers"])):
                self.nonstatic_members.add((*scope.namespace, name))
            self.bind(p.stack, name, kind, declaration_offset=name_offset)
        if not owner and "::" in name:
            p.slice[0].namespace = self.namespace_path(p.stack, name.rsplit("::", 1)[0])
        if function:
            if hasattr(symbol, "deduced_return"):
                p.slice[0].deduced_return = symbol.deduced_return
            function = operators[0]
            p[0] = {"type": "FunctionDeclaration", "name": name, "returnType": return_type,
                    "parameters": function["parameters"], "qualifiers": function["qualifiers"], "noexcept": function["noexcept"]}
            if "attributes" in function:
                p[0]["functionTypeAttributes"] = function["attributes"]
            if "trailingReturnType" in function:
                p[0]["trailingReturnType"] = function["trailingReturnType"]
            if virt:
                p[0]["virtSpecifiers"] = virt
            if self.has_placeholder_parameter(function["parameters"]):
                p[0]["abbreviated"] = True
            p.slice[0].locals = {arg["name"]: ("value_pack" if arg.get("pack") else self.declared_binding(p.stack, arg["parameterType"], parameter=True))
                                for arg in function["parameters"] if arg["name"]}
        else:
            if virt:
                raise self.source.error(virt_offset, "virtual specifier requires a function declarator")
            dims = []
            index = 0
            while index < len(operators) and operators[index]["type"] == "ArrayOperator":
                dims.append(operators[index]["size"])
                index += 1
            p[0] = {"type": "VariableDeclaration", "name": name, "dimensions": dims,
                    "variableType": self.derived_type(declared_type, operators[index:])}

            self.attach_dimension_attributes(p[0], operators[:index])

        if attrs := getattr(symbol, "id_attributes", None):
            p[0]["declaratorAttributes"] = attrs
        if owner:
            p[0]["owner"] = owner
        if specialization:
            p[0]["specialization"] = specialization

    @staticmethod
    def pointer_operators(pointers):
        return [{"type": "PointerOperator", **(op if isinstance(op, dict) else {"operator": op})}
                for op in reversed(pointers)]

    def declared_type(self, base, declarator):
        # Read from the identifier outwards. A grouped prefix binds before
        # suffixes outside the parentheses; ungrouped prefixes bind after them.
        name, operators = declarator
        operators = operators + self.pointer_operators(base["indirections"])
        if any(op["type"] == "FunctionOperator" for op in operators):
            for spec in base["specifiers"]:
                if isinstance(spec, dict) and spec["type"] in {"ClassDeclaration", "EnumDeclaration"}:
                    raise self.source.error(spec["startOffset"], "type definition in a function result type")
        return name, {"type": "Type", "specifiers": base["specifiers"], "indirections": []}, operators

    @staticmethod
    def derived_type(base, operators):
        if all(op["type"] == "PointerOperator" for op in operators):
            pointers = [{k: v for k, v in op.items() if k != "type"} if op.get("qualifiers") or op.get("gnuAttributes") or op.get("attributes") or "class" in op else op["operator"]
                        for op in reversed(operators)]
            return {**base, "indirections": pointers}
        return {**base, "declarator": operators}

    def specialization_scope(self, stack, owner, *, register=False):
        primary = ((*self.base_scope(stack, owner["qualifier"]), owner["name"]) if owner.get("qualifier")
                   else self.namespace_path(stack, owner["name"]))
        args = owner["arguments"]
        referenced = set()
        pending = list(args)
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                if value.get("type") in {"TypeName", "NameExpression", "TemplateName"}:
                    referenced.add(value["name"])
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)

        # An out-of-class member template has both class and member headers.
        # Number only the frames used by the owner, preserving parameter positions.
        indices = {}
        depth = 0
        for symbol in [*self.inherited_stack, *stack]:
            if getattr(symbol, "type", None) == "template_parameters":
                used = {p["name"]: (p["type"], depth, i) for i, p in enumerate(symbol.value)
                        if p.get("name") in referenced}
                if used:
                    indices.update(used)
                    depth += 1

        def argument_key(value):
            if isinstance(value, list):
                return [argument_key(item) for item in value]
            if not isinstance(value, dict):
                return value
            result = {k: argument_key(v) for k, v in value.items() if k != "spelling"}
            if value.get("type") in {"TypeName", "NameExpression", "TemplateName"} and value["name"] in indices:
                result["name"] = indices[value["name"]]
            return result

        # Parameter names may change on a later definition of the same partial specialization.
        key = primary, json.dumps(argument_key(owner["arguments"]), sort_keys=True)
        if register and key not in self.specialization_scopes:
            self.specialization_scopes[key] = (*primary[:-1], owner["spelling"])
            locals_ = {}
            packs = []
            for name, (kind, _, _) in indices.items():
                index = len(locals_)
                if kind == "TypeTemplateParameter":
                    locals_[name] = AliasIdentity((), frozenset(), (), parameter=index)
                elif kind == "NonTypeTemplateParameter":
                    locals_[name] = IntegralArgument(("auto",), None, index)
                else:
                    locals_[name] = "type_template"
                if any(name in getattr(sym, "template_packs", ()) for sym in [*self.inherited_stack, *stack]):
                    packs.append(index)
            context = [*stack, SimpleNamespace(locals=locals_)]
            pack = bool(args and args[-1]["type"] == "PackExpansion")
            patterns = [*args[:-1], args[-1]["pattern"]] if pack else args
            types = self.template_argument_identities(context, primary, patterns)
            if types is not None:
                pattern = ClassPattern(types[:-1], len(locals_), types[-1], tuple(packs)) if pack else ClassPattern(types, len(locals_))
                self.class_patterns.setdefault(primary, {})[pattern] = self.specialization_scopes[key]
        if key in self.specialization_scopes or primary not in self.class_patterns or indices:
            return self.specialization_scopes.get(key, primary)
        supplied = self.template_argument_identities(stack, primary, args)
        if supplied is not None:
            matches = [p for p in self.class_patterns[primary] if p.accepts(supplied)]
            for pattern in matches:
                if all(other == pattern or (other.accepts_pattern(pattern) and not pattern.accepts_pattern(other))
                       for other in matches):
                    return self.class_patterns[primary][pattern]
            if matches:
                scope = (*primary, "<ambiguous specialization>", key[1])
                self.ambiguous_specializations.add(scope)
                return scope
        return primary

    def p_template_owner(self, p):
        """template_owner : qualified_name ANGLE_OPEN template_arguments_opt ANGLE_CLOSE SCOPE
           ctor_template_owner : CTOR_TEMPLATE ANGLE_OPEN template_arguments_opt ANGLE_CLOSE SCOPE
           pointer_template_owner : POINTER_TEMPLATE ANGLE_OPEN template_arguments_opt ANGLE_CLOSE SCOPE"""
        parts = p[1].removeprefix("::").split("::")
        if self.lookup(p.stack, parts, p[1].startswith("::")) != "type_template":
            raise self.source.error(p.lexpos(1), "expected class template in declarator qualifier")
        p[0] = {"type": "TypeName", "name": p[1], "arguments": p[3],
                "spelling": self.source.spelling(p.lexpos(1), p.slice[4].endlexpos)}
        p.slice[0].namespace = self.specialization_scope(p.stack, p[0])

    def p_nested_template_owner(self, p):
        """template_owner : template_owner IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE SCOPE
           ctor_template_owner : ctor_template_owner IDENT ANGLE_OPEN template_arguments_opt ANGLE_CLOSE SCOPE"""
        if self.member_binding(p.slice[1].namespace, p[2]) != "type_template":
            raise self.source.error(p.lexpos(2), "expected a nested class template in declarator qualifier")
        p[0] = {"type": "QualifiedType", "qualifier": p[1], "name": p[2], "arguments": p[4],
                "spelling": self.source.spelling(p.lexpos(1), p.slice[5].endlexpos)}
        p.slice[0].namespace = self.specialization_scope(p.stack, p[0])
        p.slice[0].owner_name = getattr(p.slice[1], "owner_name", p[1]["name"]) + "::" + p[2]

    def p_declarator_id(self, p):
        """declarator_id : qualified_name
                         | template_owner IDENT
                         | template_owner operator_id
                         | qualified_name ANGLE_OPEN template_arguments_opt ANGLE_CLOSE
                         | overload_name"""
        if len(p) == 2:
            p[0] = p[1]
        elif p.slice[1].type == "template_owner":
            p[0] = getattr(p.slice[1], "owner_name", p[1]["name"]) + "::" + p[2]
            p.slice[0].owner = p[1]
            p.slice[0].namespace = p.slice[1].namespace
        else:
            kind = self.lookup(p.stack, p[1].removeprefix("::").split("::"), p[1].startswith("::"))
            instantiating = any(sym.type in {"instantiation_prefix", "explicit_header"} for sym in p.stack)
            friend = p.stack[-1].type == "type" and "friend" in p.stack[-1].value["specifiers"]
            if kind != "variable_template" and not ((instantiating or friend) and kind == "function_template"):
                raise self.source.error(p.lexpos(1), "expected a variable template")
            p[0] = p[1]
            p.slice[0].specialization = {"type": "TemplateId", "name": p[1], "arguments": p[3]}

    def p_direct_named(self, p):
        """direct_named : declarator_id
                        | declarator_id attribute_sequence
                        | GROUP_OPEN nested_named ')'
                        | direct_named array_suffix
                        | direct_named function_suffix"""
        source = p.slice[2] if p.slice[1].type == "GROUP_OPEN" else p.slice[1]
        for key in ("owner", "specialization", "id_attributes", "last_function"):
            if hasattr(source, key):
                setattr(p.slice[0], key, getattr(source, key))
        if p.slice[1].type == "declarator_id":
            p[0] = (p[1], [])
            if len(p) == 3:
                p.slice[0].id_attributes = p[2]
        elif p.slice[1].type == "GROUP_OPEN":
            p[0] = p[2]
        else:
            name, operators = p[1]
            if p.slice[2].type == "function_suffix":
                p.slice[0].last_function = p[2]
            operators.append(p[2])
            p[0] = (name, operators)
        if p[0][1] and p[0][1][0]["type"] == "FunctionOperator":
            p.slice[0].locals = {arg["name"]: ("value_pack" if arg.get("pack") else self.declared_binding(p.stack, arg["parameterType"], parameter=True))
                                for arg in p[0][1][0]["parameters"] if arg["name"]}
        if owner := getattr(p.slice[0], "owner", None):
            p.slice[0].namespace = self.specialization_scope(p.stack, owner)
        elif "::" in p[0][0]:
            p.slice[0].namespace = self.namespace_path(p.stack, p[0][0].rsplit("::", 1)[0])

    def p_nested_named(self, p):
        "nested_named : indirections direct_named"
        p.slice[0].id_attributes = getattr(p.slice[2], "id_attributes", None)
        p.slice[0].owner = getattr(p.slice[2], "owner", None)
        p.slice[0].specialization = getattr(p.slice[2], "specialization", None)
        name, operators = p[2]
        p.slice[0].last_function = getattr(p.slice[2], "last_function", None)
        operators.extend(self.pointer_operators(p[1]))
        p[0] = (name, operators)

    def p_abstract_type(self, p):
        """abstract_type : type
                         | type direct_abstract trailing_return_opt
           inline_type_id : enum_type
                          | enum_type direct_abstract trailing_return_opt
                          | record_type
                          | record_type direct_abstract trailing_return_opt"""
        if len(p) == 2:
            p[0] = p[1]
        else:
            self.attach_trailing_type(p, 2, 3)
            _, base, operators = self.declared_type(p[1], (None, p[2]))
            p[0] = self.derived_type(base, operators)

    def p_direct_abstract(self, p):
        """direct_abstract : GROUP_OPEN indirections ')'
                           | GROUP_OPEN indirections direct_abstract ')'
                           | array_suffix
                           | direct_abstract array_suffix
                           | function_suffix
                           | direct_abstract function_suffix"""
        if p.slice[1].type == "GROUP_OPEN":
            if not p[2] and len(p) == 4:
                raise self.source.error(p.lexpos(1), "empty parenthesized declarator")
            operators = [] if len(p) == 4 else p[3]
            p[0] = operators + self.pointer_operators(p[2])
        else:
            if p.slice[-1].type == "function_suffix":
                p.slice[0].last_function = p[len(p)-1]
            p[0] = ([] if len(p) == 2 else p[1]) + [p[len(p)-1]]

    def p_array_suffix(self, p):
        """array_suffix : '[' array_bound ']'
                        | '[' array_bound ']' attribute_sequence"""
        p[0] = {"type": "ArrayOperator", "size": p[2]}
        if len(p) == 5:
            self.check_type_attributes(p[4], "an array type")
            p[0]["attributes"] = p[4]

    def p_array_bound(self, p):
        """array_bound : empty
                       | conditional"""
        p[0] = p[1]

    def p_function_suffix(self, p):
        "function_suffix : PARAM_OPEN parameters_opt ')' fn_qualifiers noexcept_opt function_type_attributes"
        p[0] = {"type": "FunctionOperator", "parameters": p[2], "qualifiers": p[4], "noexcept": p[5]}
        if p[6]:
            p[0]["attributes"] = p[6]

    def p_function_type_attributes(self, p):
        """function_type_attributes : empty
                                    | attribute_sequence"""
        p[0] = p[1]
        if p[0]:
            self.check_type_attributes(p[0], "a function type")

    def attach_trailing_type(self, p, declarator, trailing):
        if p[trailing] is not None:
            fn = getattr(p.slice[declarator], "last_function", None)
            if fn is None:
                raise self.source.error(p.lexpos(trailing), "trailing return type requires function suffix")
            fn["trailingReturnType"] = p[trailing]

    def p_trailing_return_opt(self, p):
        """trailing_return_opt : empty
                               | ARROW abstract_type"""
        p[0] = p[2] if len(p) == 3 else None

    @staticmethod
    def attach_dimension_attributes(node, dimensions):
        if any("attributes" in op for op in dimensions):
            node["dimensionAttributes"] = [op.get("attributes", []) for op in dimensions]

    def p_simple(self, p):
        """exportable : typed_declaration
           typed_declaration : variable
                             | function
                             | class_decl
                             | enum_decl
                             | alias_decl
                             | using_decl
                             | template_decl
                             | special_function
                             | assertion"""
        p[0] = p[1]

    def p_guide_head(self, p):
        "guide_head : GUIDE_NAME PARAM_OPEN parameters_opt ')'"
        p[0] = {"type": "DeductionGuide", "name": p[1], "parameters": p[3]}
        p.slice[0].locals = p.slice[2].locals

    def p_deduction_guide(self, p):
        """typed_declaration : guide_head ARROW named_type ';'
                             | EXPLICIT guide_head ARROW named_type ';'
                             | EXPLICIT EXPLICIT_OPEN conditional ')' guide_head ARROW named_type ';'"""
        head, target = p[len(p)-4], p[len(p)-2]
        if target.get("name") != head["name"] or "arguments" not in target:
            raise self.source.error(p.lexpos(len(p)-2), "deduction guide requires a specialization of its class template")
        p[0] = {**head, "target": target, "explicit": p[3] if len(p) == 9 else len(p) == 6}

    def p_assertion(self, p):
        """assertion : STATIC_ASSERT '(' conditional ')' ';'
                     | STATIC_ASSERT '(' conditional ',' unsuffixed_string ')' ';'"""
        p[0] = {"type": "StaticAssertion", "test": p[3], "message": p[5] if len(p) == 8 else None}

    def p_function(self, p):
        """function : declared_head HEAD_END block
                    | declared_head try_block"""
        if p[1]["type"] != "FunctionDeclaration":
            raise self.source.error(p.lexpos(2), "expected a function declarator before body")
        if "specialization" in p[1] and "friend" in p[1]["returnType"]["specifiers"]:
            raise self.source.error(p.lexpos(2), "friend declaration with a template-id cannot define a function")
        p[0] = {**p[1], "body": p[len(p)-1]}

    def p_fn_qualifiers(self, p):
        """fn_qualifiers : empty
                         | fn_qualifiers SPECIFIER
                         | fn_qualifiers '&'
                         | fn_qualifiers AND"""
        if len(p) == 2:
            p[0] = []
        else:
            if p[2] not in {"const", "volatile", "&", "bitand", "&&", "and"}:
                raise self.source.error(p.lexpos(2), "invalid function qualifier")
            if p[1] and p[1][-1] in {"&", "bitand", "&&", "and"}:
                raise self.source.error(p.lexpos(2), "unexpected qualifier after function ref-qualifier")
            if p[2] in p[1]:
                raise self.source.error(p.lexpos(2), "duplicate function qualifier")
            p[1].append(p[2])
            p[0] = p[1]

    def p_noexcept(self, p):
        """noexcept_opt : empty
                        | NOEXCEPT
                        | THROW '(' ')'
                        | NOEXCEPT '(' expression ')'"""
        if p.slice[1].type == "THROW":
            p[0] = {"type": "EmptyThrowSpecification"}
        else:
            p[0] = p[3] if len(p) == 5 else p[1] == "noexcept"

    def p_parameters_opt(self, p):
        """parameters_opt : empty
                          | parameters
                          | ELLIPSIS
                          | parameters ',' ELLIPSIS
                          | parameters ELLIPSIS"""
        if p.slice[-1].type == "ELLIPSIS":
            params = [] if len(p) == 2 else p[1]
            params.append({"type": "Ellipsis", "name": None})
            p[0] = params
        else:
            p[0] = p[1] or []

    def p_parameters(self, p):
        """parameters : parameter
                      | parameters ',' parameter"""
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[1].append(p[3])
            p[0] = p[1]

    def p_parameter(self, p):
        """parameter : abstract_type
                     | abstract_type '=' initializer
                     | type direct_named
                     | type direct_named gnu_attribute
                     | type direct_named gnu_attribute '=' initializer
                     | type direct_named '=' initializer"""
        name, parameter_type = None, p[1]
        if p.slice[1].type == "type":
            name, base, operators = self.declared_type(p[1], p[2])
            parameter_type = self.derived_type(base, operators)
            opening = next((sym for sym in reversed(p.stack) if sym.type == "PARAM_OPEN"), None)
            if opening is None:
                opening = self.inherited_stack[-1]
            opening.locals[name] = self.declared_binding(p.stack, parameter_type, parameter=True)
        p[0] = {"type": "Parameter", "parameterType": parameter_type,
                "name": name, "default": p[len(p)-1] if p.slice[-1].type == "initializer" else None}

        if len(p) >= 4 and p.slice[3].type == "gnu_attribute":
            p[0]["gnuAttributes"] = [p[3]]
        if len(p) >= 3 and (attrs := getattr(p.slice[2], "id_attributes", None)):
            p[0]["declaratorAttributes"] = attrs

    def p_attributed_identifier(self, p):
        """attributed_identifier : IDENT
                                 | IDENT attribute_sequence"""
        p[0] = p[1]
        if len(p) == 3:
            p.slice[0].id_attributes = p[2]

    def p_grouped_pack(self, p):
        """grouped_pack : GROUP_OPEN indirections ELLIPSIS attributed_identifier ')'
                        | GROUP_OPEN indirections grouped_pack ')'
                        | grouped_pack function_suffix
                        | grouped_pack array_suffix"""
        if p.slice[1].type == "GROUP_OPEN":
            source = p.slice[4] if len(p) == 6 else p.slice[3]
            name, operators = (p[4], []) if len(p) == 6 else p[3]
            p[0] = (name, operators + self.pointer_operators(p[2]))
        else:
            source = p.slice[1]
            name, operators = p[1]
            p[0] = (name, operators + [p[2]])
        p.slice[0].id_attributes = getattr(source, "id_attributes", None)

    def p_ungrouped_pack(self, p):
        """ungrouped_pack : PACK
                          | PACK attributed_identifier
                          | ungrouped_pack function_suffix
                          | ungrouped_pack array_suffix"""
        if p.slice[1].type == "PACK":
            p[0] = (p[2] if len(p) == 3 else None, [])
        else:
            name, operators = p[1]
            p[0] = (name, operators + [p[2]])

        source = p.slice[-1] if p.slice[1].type == "PACK" else p.slice[1]
        p.slice[0].id_attributes = getattr(source, "id_attributes", None)

    def p_pack_parameter(self, p):
        """parameter : type ungrouped_pack
                     | type grouped_pack"""
        name, base, operators = self.declared_type(p[1], p[2])
        target = self.derived_type(base, operators)
        if name:
            opening = next((sym for sym in reversed(p.stack) if sym.type == "PARAM_OPEN"), None)
            (opening or self.inherited_stack[-1]).locals[name] = "value_pack"
        p[0] = {"type": "Parameter", "parameterType": target, "name": name, "default": None, "pack": True}

        if attrs := getattr(p.slice[2], "id_attributes", None):
            p[0]["declaratorAttributes"] = attrs

    def p_block(self, p):
        "block : BLOCK_OPEN statements '}'"
        p[0] = {"type": "CompoundStatement", "statements": p[2]}

    def p_statements(self, p):
        """statements : empty
                      | statements statement"""
        if len(p) == 2:
            p[0] = []
        else:
            p[1].append(p[2])
            p[0] = p[1]

    def p_statement(self, p):
        """statement : variable
                     | block
                     | alias_decl
                     | using_decl
                     | enum_decl
                     | class_decl
                     | assertion
                     | expression ';'
                     | ';'
                     | RETURN ';'
                     | RETURN expression_or_braces ';'"""
        kind = p.slice[1].type
        if kind in {"block", "variable", "alias_decl", "using_decl", "enum_decl", "class_decl", "assertion"}:
            p[0] = p[1]
        elif kind == "RETURN":
            self.check_coroutine_context(p)
            p[0] = {"type": "ReturnStatement", "expression": p[2] if len(p) == 4 else None}
        else:
            p[0] = {"type": "ExpressionStatement", "expression": None if kind == ";" else p[1]}

    def p_if_statement(self, p):
        """statement : IF constexpr_opt '(' selection_condition ')' controlled %prec IF
                     | IF constexpr_opt '(' selection_condition ')' controlled ELSE controlled"""
        p[0] = {"type": "IfStatement", **p[4], "then": p[6], "else": p[8] if len(p) == 9 else None}
        if p[2]:
            p[0]["constexpr"] = True

    def p_constexpr_opt(self, p):
        """constexpr_opt : empty
                         | IF_CONSTEXPR"""
        p[0] = bool(p[1])

    def p_selection_condition(self, p):
        """selection_condition : condition
                               | for_init condition"""
        p[0] = {"test": p[len(p)-1]}
        if len(p) == 3:
            p[0]["init"] = p[1]

    def p_condition(self, p):
        """condition : expression
                     | init_declarators
                     | attribute_sequence init_declarators"""
        if p.slice[1].type == "expression":
            p[0] = p[1]
            return
        specs, declarations = p[len(p)-1]
        for spec in specs:
            if isinstance(spec, dict) and spec["type"] == "EnumDeclaration":
                raise self.source.error(spec["startOffset"], "enum definition in a condition")
        node = declarations[0]
        if (len(declarations) != 1 or node["type"] != "VariableDeclaration" or node["dimensions"]
                or node["initializer"] is None or node["initializer"]["type"] == "DirectInitializer"):
            raise self.source.error(p.lexpos(1), "expected one initialized condition variable")
        self.require_type_specifiers(node["variableType"], p.lexpos(1), "condition", allow_constexpr=True)
        p[0] = {**node, "attributes": p[1]} if len(p) == 3 else node

    def p_while_statement(self, p):
        "statement : WHILE '(' condition ')' controlled"
        p[0] = {"type": "WhileStatement", "test": p[3], "body": p[5]}

    def p_condition_opt(self, p):
        """condition_opt : empty
                         | condition"""
        p[0] = p[1]

    def p_expression_opt(self, p):
        """expression_opt : expression
                          | empty"""
        p[0] = p[1]

    def p_controlled(self, p):
        "controlled : control_scope statement"
        p[0] = p[2]

    def p_control_scope(self, p):
        "control_scope :"
        owner = self.enclosing_control(p.stack, {"IF", "SWITCH", "WHILE", "FOR", "DO", "range_head"})
        p.slice[0].control_names = owner.locals if owner is not None else {}
        p.slice[0].locals = {}

    def p_for(self, p):
        """statement : FOR '(' for_init condition_opt ';' expression_opt ')' controlled
                     | range_head controlled"""
        if len(p) == 3:
            p[0] = {**p[1], "body": p[2]}
        else:
            p[0] = {"type": "ForStatement", "init": p[3], "test": p[4], "update": p[6], "body": p[8]}

    def p_range_head(self, p):
        """range_head : FOR '(' type IDENT ':' expression_or_braces ')'
                      | FOR '(' for_init type IDENT ':' expression_or_braces ')'"""
        name = p[len(p)-4]
        p[0] = {"type": "RangeForStatement", "variableType": p[len(p)-5], "name": name, "range": p[len(p)-2]}
        if len(p) == 9:
            p[0]["init"] = p[3]
        if name in p.slice[1].locals:
            raise self.source.error(p.lexpos(len(p)-4), f"redeclaration of control variable {name!r}")
        p.slice[0].locals = {**p.slice[1].locals, name: "value"}

    def p_binding_range_head(self, p):
        """range_head : FOR '(' binding_head ':' expression_or_braces ')'
                      | FOR '(' for_init binding_head ':' expression_or_braces ')'"""
        binding = p[len(p)-4]
        p[0] = {"type": "RangeForStatement", "binding": binding, "range": p[len(p)-2]}
        if len(p) == 8:
            p[0]["init"] = p[3]
        for name in binding["names"]:
            if name in p.slice[1].locals:
                raise self.source.error(p.lexpos(len(p)-4), f"redeclaration of control variable {name!r}")
        p.slice[0].locals = {**p.slice[1].locals, **dict.fromkeys(binding["names"], "value")}

    def p_for_init(self, p):
        """for_init : variable
                    | attribute_sequence variable
                    | alias_decl
                    | expression_opt ';'"""
        if p.slice[1].type == "alias_decl" and p[1].get("syntax") == "using":
            raise self.source.error(p.lexpos(1), "alias-declaration in initializer requires C++23")
        p[0] = {**p[2], "attributes": p[1]} if p.slice[1].type == "attribute_sequence" else p[1]

    @staticmethod
    def enclosing_control(stack, kinds):
        for symbol in reversed(stack):
            if symbol.type in kinds:
                return symbol
            if symbol.type in {"lambda_intro", "declared_head", "special_head", "class_head"}:
                break
        return None

    def p_labeled_statement(self, p):
        """statement : LABEL_NAME ':' statement
                     | CASE conditional ':' statement
                     | DEFAULT ':' statement"""
        kind = p.slice[1].type
        if kind == "LABEL_NAME":
            p[0] = {"type": "LabeledStatement", "label": p[1], "statement": p[3]}
        else:
            switch = self.enclosing_control(p.stack, {"SWITCH"})
            if switch is None:
                raise self.source.error(p.lexpos(1), "case or default label outside switch")
            if kind == "DEFAULT":
                if getattr(switch, "has_default", False):
                    raise self.source.error(p.lexpos(1), "duplicate default label")
                switch.has_default = True
            p[0] = {"type": "CaseStatement", "value": p[2] if kind == "CASE" else None, "statement": p[len(p)-1]}

    def p_switch_statement(self, p):
        "statement : SWITCH '(' selection_condition ')' controlled"
        p[0] = {"type": "SwitchStatement", **p[3], "body": p[5]}

    def p_do_statement(self, p):
        "statement : DO controlled WHILE '(' expression ')' ';'"
        p[0] = {"type": "DoWhileStatement", "body": p[2], "test": p[5]}

    def p_goto_statement(self, p):
        "statement : GOTO IDENT ';'"
        p[0] = {"type": "GotoStatement", "label": p[2]}

    def check_coroutine_context(self, p):
        if self is not _state.grammar:
            return
        word, offset = p[1], p.lexpos(1)
        in_handler = unevaluated = in_body = False
        for symbol in reversed([*self.inherited_stack, *p.stack]):
            kind = getattr(symbol, "type", None)
            in_handler |= kind == "catch_head"
            unevaluated |= kind in {"SIZEOF", "NOEXCEPT", "DECLTYPE", "REQUIRES"}
            in_body |= kind == "BLOCK_OPEN"
            if kind in {"class_head", "lambda_intro"}:
                break
            if kind == "lambda_signature" or kind in {"declared_head", "special_head"} and symbol.value["type"] in {
                "FunctionDeclaration", "ConstructorDeclaration", "DestructorDeclaration", "ConversionFunctionDeclaration"
            }:
                if not in_body:
                    break
                if word == "return":
                    symbol.ordinary_return = offset
                    key = getattr(symbol, "deduced_return", None)
                    if key is not None and not getattr(symbol, "declared_result", False):
                        expr = p[2] if len(p) == 4 else None
                        receiver = self.receiver_binding(p.stack, expr) if expr else "void"
                        identity = self.argument_identity(p.stack, expr) if expr else AliasIdentity(("void",), frozenset(), ())
                        declared = symbol.value.get("returnType") or {"specifiers": ["auto"], "indirections": []}
                        if "auto" in declared["specifiers"] and not declared["indirections"]:
                            if identity:
                                if identity.layers and identity.layers[-1].operator in ("&", "&&"):
                                    identity = identity._replace(layers=identity.layers[:-1])
                                identity = identity.parameter_type()
                            if isinstance(receiver, tuple) and receiver[0] in _INDIRECT_BINDINGS and receiver[2] and isinstance(receiver[2][0], ReceiverArray):
                                receiver = (*receiver[:2], ("pointer", *receiver[2][1:]))
                        self.deduced_returns.setdefault(key, set()).add((receiver, identity))
                    if getattr(symbol, "coroutine", False):
                        raise self.source.error(offset, "ordinary return in a coroutine")
                    return
                decl = symbol.value
                if word != "co_return" and (in_handler or unevaluated):
                    raise self.source.error(offset, f"{word} cannot suspend in this context")
                if decl.get("name") == "main" and not self.namespace([*self.inherited_stack, *p.stack]):
                    raise self.source.error(offset, "the main function cannot be a coroutine")
                if decl.get("type") in {"ConstructorDeclaration", "DestructorDeclaration"}:
                    raise self.source.error(offset, "constructor or destructor cannot be a coroutine")
                specs = decl.get("specifiers", (decl.get("returnType") or {}).get("specifiers", []))
                if "constexpr" in specs or "consteval" in specs:
                    raise self.source.error(offset, "constant-evaluated function cannot be a coroutine")
                if any(arg["type"] == "Ellipsis" for arg in decl.get("parameters") or []):
                    raise self.source.error(offset, "variadic function cannot be a coroutine")
                if hasattr(symbol, "ordinary_return"):
                    raise self.source.error(symbol.ordinary_return, "ordinary return in a coroutine")
                symbol.coroutine = True
                return
        if word != "return":
            raise self.source.error(offset, f"{word} requires a function body")

    def p_coroutine_return(self, p):
        """statement : CO_RETURN ';'
                     | CO_RETURN expression_or_braces ';'"""
        self.check_coroutine_context(p)
        p[0] = {"type": "CoroutineReturnStatement", "operand": p[2] if len(p) == 4 else None}

    def p_jump(self, p):
        """statement : BREAK ';'
                     | CONTINUE ';'"""
        targets = {"FOR", "range_head", "WHILE", "DO"}
        if p.slice[1].type == "BREAK":
            targets.add("SWITCH")
        if self.enclosing_control(p.stack, targets) is None:
            raise self.source.error(p.lexpos(1), f"no enclosing target for {p[1]}")
        p[0] = {"type": p[1].capitalize() + "Statement"}

    def p_error(self, token):
        if token is None:
            raise self.source.error(len(self.source.source), "unexpected end of file")
        raise self.source.error(token.lexpos, f"unexpected {token.value!r}")

    def reset_names(self):
        self.lambda_types = {}
        self.deduced_returns = {}
        self.pending_destructors = {}
        # These target-provided names can also be supplied by a system-header typedef.
        self.bindings = {(name,): "type" for name in ("_Float32", "_Float64", "_Float128", "_Float32x", "_Float64x", "__int128_t", "__uint128_t")}
        self.class_scopes = set()
        self.nonstatic_members = set()
        self.class_aliases = {}
        self.implicit_conversions = {}
        self.converting_constructors = {}
        self.ambiguous_specializations = set()
        self.class_patterns = {}
        self.specialization_scopes = {}
        self.template_parameters = {}
        self.base_scopes = {}
        self.namespaces = {()}
        self.enum_tags = set()
        self.enum_records = {}
        self.enum_origins = {}
        self.enum_targets = {}
        self.injected_namespaces = {}
        self.injected_only = set()
        self.using_origins = {}
        self.namespace_aliases = {}
        self.using_namespaces = {}
        self.inline_namespaces = set()
        self.inline_children = {}
        self.unnamed_namespaces = {}
        self.lookup_offset = 0
        self.lookup_components = ()
        self.inherited_stack = ()

    def probe_clause(self, tokens, stack, *, type_id=False):
        probe, table = ((_state.type_grammar, _state.type_parser) if type_id
                        else (_state.parameter_grammar, _state.parameter_parser))
        # Each invocation owns its LR stack, including probes inside sizeof bounds.
        parser = copy(table)
        previous = probe.inherited_stack
        inherited = [*self.inherited_stack, *stack, SimpleNamespace(locals={})]
        probe.source = self.source
        probe.lambda_types = self.lambda_types
        probe.deduced_returns = self.deduced_returns
        probe.bindings = self.bindings
        probe.class_scopes = self.class_scopes
        probe.nonstatic_members = self.nonstatic_members
        probe.class_aliases = self.class_aliases
        probe.implicit_conversions = self.implicit_conversions
        probe.converting_constructors = self.converting_constructors
        probe.ambiguous_specializations = self.ambiguous_specializations
        probe.class_patterns = self.class_patterns
        probe.specialization_scopes = self.specialization_scopes
        probe.template_parameters = self.template_parameters
        probe.base_scopes = self.base_scopes
        probe.namespaces = self.namespaces
        probe.enum_tags = self.enum_tags
        probe.enum_records = self.enum_records
        probe.enum_origins = self.enum_origins
        probe.enum_targets = self.enum_targets
        probe.injected_namespaces = self.injected_namespaces
        probe.injected_only = self.injected_only
        probe.using_origins = self.using_origins
        probe.namespace_aliases = self.namespace_aliases
        probe.using_namespaces = self.using_namespaces
        probe.unnamed_namespaces = self.unnamed_namespaces
        probe.inline_namespaces = self.inline_namespaces
        probe.inline_children = self.inline_children
        probe.inherited_stack = inherited
        stream = probe.parser_tokens((copy(token) for token in tokens), parser)
        try:
            parser.parse(lexer=self.source, tokenfunc=lambda: next(stream, None), tracking=True)
        except CParseError:
            return False
        finally:
            probe.inherited_stack = previous
        return True

    def parser_tokens(self, raw, parser):
        pending = deque()
        depth = 0
        attribute_depth = None
        gnu_attribute = False

        def peek(i):
            while len(pending) <= i:
                part = next(raw, None)
                if part is None:
                    return None
                pending.append(part)
            return pending[i]

        def template_end(at, opening):
            index, depth, groups = opening+1, 1, []
            while (part := at(index)) is not None:
                if part.type in {"(", "[", "{"}:
                    groups.append({"(": ")", "[": "]", "{": "}"}[part.type])
                elif groups and part.type == groups[-1]:
                    groups.pop()
                elif not groups:
                    if part.type in {";", ")", "]", "}"}:
                        return None
                    if part.value == "<":
                        depth += 1
                    elif part.value in {">", ">>"}:
                        depth -= len(part.value)
                        if depth <= 0:
                            return index if depth == 0 else None
                index += 1
            return None

        def constructor_owner_ahead(opening, class_name):
            end = template_end(peek, opening)
            if end is None or not peek(end+1) or peek(end+1).type != "SCOPE":
                return False
            index = end+2
            while peek(index) and peek(index).type == "IDENT":
                after = index + 1
                if peek(after) and peek(after).type == "<":
                    nested_end = template_end(peek, after)
                    if nested_end is None:
                        return False
                    after = nested_end + 1
                if not peek(after) or peek(after).type != "SCOPE":
                    break
                class_name = peek(index).value
                index = after + 1
            if peek(index) and peek(index).type == "~":
                index += 1
            return peek(index) and peek(index).value == class_name and peek(index+1) and peek(index+1).type == "("

        def deferred_group(opening, closing, kind):
            tokens, level = [opening], 1
            while level:
                part = pending.popleft() if pending else next(raw, None)
                if part is None:
                    raise self.source.error(len(self.source.source), "unexpected end of file")
                tokens.append(part)
                level += (part.type == opening.type) - (part.type == closing)
            group = copy(opening)
            group.type, group.value, group.endlexpos = kind, tokens, tokens[-1].endlexpos
            return group

        def member_pointer(at):
            i = int(at(0) is not None and at(0).type == "SCOPE")
            names = []
            while at(i) and at(i).type == "IDENT" and at(i+1) and at(i+1).type == "SCOPE":
                names.append(at(i).value)
                i += 2
            absolute = "::" if at(0) and at(0).type == "SCOPE" else ""
            if names and at(i) and at(i).type == "*":
                return MemberPointerMatch(absolute + "::".join(names), i+1, i+1)
            if at(i) and at(i).type == "IDENT" and at(i+1) and at(i+1).type == "<":
                names.append(at(i).value)
                prefix_end = i+1
                end = template_end(at, i+1)
                if end is not None and at(end+1) and at(end+1).type == "SCOPE" and at(end+2) and at(end+2).type == "*":
                    return MemberPointerMatch(absolute + "::".join(names), end+3, prefix_end)
            return None

        def pointer_prefix_end(index):
            while peek(index):
                owner = member_pointer(lambda n: peek(index+n))
                if owner:
                    index += owner.token_count
                elif peek(index).type in {"*", "&", "AND"}:
                    index += 1
                else:
                    break
                while peek(index):
                    if peek(index).value in {"const", "volatile", "__restrict", "__restrict__"}:
                        index += 1
                    elif peek(index).type == "[" and peek(index+1) and peek(index+1).type == "[":
                        depth, index = 2, index+2
                        while depth and peek(index):
                            depth += (peek(index).type == "[") - (peek(index).type == "]")
                            index += 1
                    elif peek(index).value in {"__attribute", "__attribute__"} and peek(index+1) and peek(index+1).type == "(":
                        level, index = 1, index+2
                        while level and peek(index):
                            level += (peek(index).type == "(") - (peek(index).type == ")")
                            index += 1
                    else:
                        break
            return index

        def grouped_name(index):
            index = pointer_prefix_end(index)
            if peek(index) is None:
                return None
            if peek(index).type == "(":
                close = grouped_name(index+1)
                if close is None:
                    return None
                index = close+1
            elif peek(index).type == "IDENT":
                index += 1
            else:
                return None
            while peek(index) and peek(index).type in {"(", "["}:
                opening = peek(index).type
                closing = ")" if opening == "(" else "]"
                level = 1
                index += 1
                while level and peek(index):
                    level += (peek(index).type == opening) - (peek(index).type == closing)
                    index += 1
                if level:
                    return None
            return index if peek(index) and peek(index).type == ")" else None

        def abstract_pointer_group():
            end = pointer_prefix_end(0)
            return end > 0 and peek(end) is not None and peek(end).type == ")"

        def in_cast_type(scope):
            index = len(scope)-1
            while index >= 0 and scope[index].type in {"SPECIFIER", "modifier", "modifiers"}:
                index -= 1
            return (index > 0 and scope[index].type == "<"
                    and scope[index-1].type in {"STATIC_CAST", "CONST_CAST", "REINTERPRET_CAST", "DYNAMIC_CAST"})

        def guide_ahead():
            level, index = 1, 1
            while (part := peek(index)) is not None:
                level += (part.type == "(") - (part.type == ")")
                if not level:
                    return peek(index+1) is not None and peek(index+1).type == "ARROW"
                index += 1
            return False

        def parameters_ahead(scope):
            first = peek(0)
            if first and first.type in {"STRUCT", "CLASS", "UNION", "ENUM"}:
                return True
            if first and first.type == "[" and peek(1) and peek(1).type == "[":
                return True
            if first is None or first.type in {")", "ELLIPSIS"}:
                return True
            if first.type not in {"BUILTIN", "PACK_ELEMENT", "MAKE_INTEGER_SEQ", "GNU_TYPEOF", "SPECIFIER", "TYPE_NAME", "IDENT", "SCOPE", "TYPENAME", "DECLTYPE"}:
                return False
            if first.type == "SPECIFIER" or first.type == "BUILTIN" and peek(1) and peek(1).type not in {"(", "{"}:
                return True
            if first.type == "IDENT" and not (peek(1) and (peek(1).type == "SCOPE" or
                    first.value in TYPE_TRANSFORMS and peek(1).type == "(")):
                binding = self.lookup(scope, [first.value], False)
                if not isinstance(binding, tuple) and binding not in {"type", "type_template"}:
                    return False
                if binding == "type" and peek(1) and peek(1).type == "ELLIPSIS":
                    return True
            level, index = 1, 0
            while (part := peek(index)) is not None:
                level += (part.type == "(") - (part.type == ")")
                if not level:
                    return self.probe_clause(list(pending)[:index], scope)
                index += 1
            return True

        def type_id_ahead(prefix, after_keyword, *, alignment=False):
            first = peek(0)
            if first is None or first.type not in {"BUILTIN", "STRUCT", "CLASS", "UNION", "ENUM", "PACK_ELEMENT", "MAKE_INTEGER_SEQ", "GNU_TYPEOF", "SPECIFIER", "IDENT", "SCOPE", "TYPENAME", "DECLTYPE"}:
                return False
            if first.type == "IDENT" and not (peek(1) and (peek(1).type == "SCOPE" or
                    first.value in TYPE_TRANSFORMS and peek(1).type == "(")):
                binding = self.lookup(parser.symstack[:prefix], [first.value], False)
                if not isinstance(binding, tuple) and binding not in {"type", "type_template"}:
                    return False
            index, level = 0, 1
            while (part := peek(index)) is not None:
                level += (part.type == "(") - (part.type == ")")
                if not level:
                    following = peek(index+1)
                    if not after_keyword and (following is None or following.type not in {
                        "[", "IDENT", "SCOPE", "BUILTIN", "NUMBER", "CHARACTER", "STRING", "(", "!", "~", "*", "&",
                        "+", "-", "INC", "DEC", "THIS", "TRUE", "FALSE", "NULLPTR", "SIZEOF", "ALIGNOF", "GNU_ALIGNOF", "TYPEID",
                        "NOEXCEPT", "CO_AWAIT", "BUILTIN_BIT_CAST", "GNU_TYPEOF", "UNARY_TRAIT", "BINARY_TRAIT", "VARIADIC_TRAIT", "REQUIRES", "DELETE", "NEW", "STATIC_CAST", "DYNAMIC_CAST", "CONST_CAST", "REINTERPRET_CAST",
                    }):
                        return False
                    end = index - 1 if alignment and index and pending[index-1].type == "ELLIPSIS" else index
                    return self.probe_clause(list(pending)[:end], parser.symstack[:prefix], type_id=True)
                index += 1
            return False

        previous = previous_value = None
        while (token := pending.popleft() if pending else next(raw, None)) is not None:
            self.lookup_offset = token.lexpos
            self.lookup_components = ()
            if attribute_depth is None and token.type == "[" and peek(0) and peek(0).type == "[" and stack_prefix(parser, "ATTR_OPEN") is not None:
                token.type = "ATTR_OPEN"
                token.endlexpos = pending.popleft().endlexpos
                attribute_depth = 0
            elif attribute_depth is None and token.value in {"__attribute", "__attribute__"} and stack_prefix(parser, "GNU_ATTRIBUTE") is not None:
                token.type = "GNU_ATTRIBUTE"
                gnu_attribute, attribute_depth = True, 0
            elif attribute_depth is not None:
                if not gnu_attribute and not attribute_depth and token.type == "]" and peek(0) and peek(0).type == "]":
                    token.type = "ATTR_CLOSE"
                    token.endlexpos = pending.popleft().endlexpos
                    attribute_depth = None
                elif token.type in {"(", "[", "{"}:
                    attribute_depth += 1
                elif token.type in {")", "]", "}"}:
                    attribute_depth -= 1
                    if gnu_attribute and not attribute_depth:
                        gnu_attribute, attribute_depth = False, None
                elif attribute_depth > (2 if gnu_attribute else 0):
                    token.type, token.value = "ATTR_ATOM", token.spelling
                elif self.source.attribute_identifier(token) and not (
                    token.type == "USING" and previous == "ATTR_OPEN"
                ):
                    token.type = "ATTR_NAME"
                previous, previous_value = token.type, token.value
                yield token
                continue
            if token.type in {"MODULE_CANDIDATE", "IMPORT_CANDIDATE"}:
                kind = token.value.upper()
                following = peek(0)
                if following is not None and following.type in {"IDENT", "HEADER", ":", ";"} and stack_prefix(parser, kind) is not None:
                    token.type = kind
                else:
                    token.type = "IDENT"
            if (token.type == "IDENT" and token.value in TYPE_TRANSFORMS and peek(0) and peek(0).type == "("
                    and stack_prefix(parser, "TYPE_TRANSFORM") is not None):
                token.type = "TYPE_TRANSFORM"
            if token.type == "IDENT" and token.value in TYPE_TRAITS and peek(0) and peek(0).type == "(":
                trait = TYPE_TRAITS[token.value]
                if stack_prefix(parser, trait) is not None:
                    token.type = trait
            if token.value == "extern" and peek(0) and peek(0).type == "TEMPLATE" and stack_prefix(parser, "EXTERN_TEMPLATE") is not None:
                token.type = "EXTERN_TEMPLATE"
            if token.value == "extern" and peek(0) and peek(0).type == "STRING" and stack_prefix(parser, "LINKAGE_EXTERN") is not None:
                token.type = "LINKAGE_EXTERN"
            if token.type == "FRIEND" and peek(0) and peek(0).type in {"CLASS", "STRUCT", "UNION"}:
                if stack_prefix(parser, "FRIEND_KEY") is not None:
                    token.type = "FRIEND_KEY"
            if token.type == "OPERATOR" and stack_prefix(parser, "CONVERSION_OPERATOR") is not None:
                following = peek(0)
                if following and following.type in {"IDENT", "BUILTIN", "SPECIFIER", "SCOPE", "TYPENAME", "DECLTYPE",
                                                     "CLASS", "STRUCT", "UNION", "ENUM", "GNU_TYPEOF", "PACK_ELEMENT",
                                                     "MAKE_INTEGER_SEQ"}:
                    token.type = "CONVERSION_OPERATOR"
            if previous == "EXPLICIT" and token.type == "(" and stack_prefix(parser, "EXPLICIT_OPEN") is not None:
                token.type = "EXPLICIT_OPEN"
            if token.type in {"CLASS", "STRUCT", "UNION", "ENUM"} and stack_prefix(parser, "ELAB_KEY") is not None:
                index = int(peek(0) is not None and peek(0).type == "SCOPE")
                if peek(index) and peek(index).type == "IDENT":
                    index += 1
                    while peek(index) and peek(index).type == "SCOPE" and peek(index+1) and peek(index+1).type == "IDENT":
                        index += 2
                    following = peek(index)
                    template_id = following and following.type == "<" and token.type != "ENUM"
                    if template_id:
                        end = template_end(peek, index)
                        following = peek(end+1) if end is not None else None
                    if following and (following.type in {"*", "&", "AND", "IDENT", "SPECIFIER", ")", ","}
                                      or template_id and following.type == "("
                                      or following.type == ";" and previous == "="
                                      or following.type == "[" and peek(index+1) and peek(index+1).type != "["):
                        if following.value != "final" and not (token.type == "CLASS" and following.type == "," and previous in {"ANGLE_OPEN", ","}):
                            token.type = "ELAB_KEY"
            if previous == "IF" and token.value == "constexpr":
                token.type = "IF_CONSTEXPR"
            if token.type == "STRING" and previous == "OPERATOR" and not token.value.endswith('"'):
                token.type = "UD_STRING"
            if token.type == "REQUIRES" and stack_prefix(parser, "NESTED_REQUIRES") is not None:
                token.type = "NESTED_REQUIRES"
            after_nested_type = (previous == "IDENT" and len(parser.symstack) >= 3
                                 and parser.symstack[-2].type == "MEMBER_TYPE_SCOPE")
            if token.type == "SCOPE" and (previous == "ANGLE_CLOSE" or after_nested_type):
                end = parser.symstack[-4:]
                explicit = peek(0) and peek(0).type == "TEMPLATE"
                member = peek(1) if explicit else peek(0)
                following = peek(2 if explicit else 1) if member else None
                has_arguments = following and following.type == "<"
                if explicit and not has_arguments:
                    member = None  # A template-template argument names the template without forming a type-id.
                kinds = {"type_template"} if has_arguments else {"type", "type_template"}
                if (member and member.type == "IDENT" and stack_prefix(parser, "MEMBER_TYPE_SCOPE") is not None
                        and [part.type for part in end] == ["TYPE_NAME", "ANGLE_OPEN", "template_arguments_opt", "ANGLE_CLOSE"]):
                    owner = {"name": end[0].value, "arguments": end[2].value}
                    scope = self.specialization_scope(parser.symstack[:-4], owner)
                    if self.member_binding(scope, member.value) in kinds:
                        token.type = "MEMBER_TYPE_SCOPE"
                if (after_nested_type and member and member.type == "IDENT"
                        and stack_prefix(parser, "MEMBER_TYPE_SCOPE") is not None):
                    parent = self.base_scope(parser.symstack[:-3], parser.symstack[-3].value)
                    scope = self.expand_class_alias((*parent, parser.symstack[-1].value), include_last=True)
                    if self.member_binding(scope, member.value) in kinds:
                        token.type = "MEMBER_TYPE_SCOPE"
                if token.type == "SCOPE" and stack_prefix(parser, "TEMPLATE_MEMBER_SCOPE") is not None:
                    token.type = "TEMPLATE_MEMBER_SCOPE"
            if token.type == "SCOPE" and previous == ")" and stack_prefix(parser, "DECLTYPE_SCOPE") is not None:
                token.type = "DECLTYPE_SCOPE"
            if token.type == "SCOPE" and stack_prefix(parser, "DEP_SCOPE") is not None and peek(0) and peek(0).type in {"IDENT", "TEMPLATE"}:
                token.type = "DEP_SCOPE"
            if token.type == "[" and stack_prefix(parser, "OP_ARRAY") is not None and peek(0) and peek(0).type == "]":
                token.type, token.value = "OP_ARRAY", "[]"
                token.endlexpos = pending.popleft().endlexpos
            if token.type == "[" and stack_prefix(parser, "LAMBDA_OPEN") is not None and stack_prefix(parser, "[") is None:
                token.type = "LAMBDA_OPEN"
            if token.type == "IDENT" and token.value in {"final", "override"} and stack_prefix(parser, token.value.upper()) is not None:
                token.type = token.value.upper()
            elif token.type in {"IDENT", "~", "SCOPE"} and (
                stack_prefix(parser, "CTOR_NAME") is not None or stack_prefix(parser, "DTOR_NAME") is not None
            ):
                special = self.special_name(token, peek, parser)
                if special:
                    token.type, token.value, length = special
                    for _ in range(length):
                        token.endlexpos = pending.popleft().endlexpos
            if token.type in {"IDENT", "SCOPE"} and stack_prefix(parser, "MEMBER_POINTER") is not None:
                owner = member_pointer(lambda i: token if i == 0 else peek(i-1))
                if owner:
                    prefix = stack_prefix(parser, "MEMBER_POINTER")
                    parts = owner.name.removeprefix("::").split("::")
                    scope = parser.symstack[:prefix]
                    known = self.lookup(scope, parts, owner.name.startswith("::"))
                    dependent = any(parts[0] in getattr(sym, "template_types", ()) for sym in [*self.inherited_stack, *scope])
                    if known not in {"type", "type_template"} and not dependent:
                        raise self.source.error(token.lexpos, "expected class name in pointer-to-member declarator")
                    token.type = "MEMBER_POINTER" if owner.token_count == owner.prefix_count else "POINTER_TEMPLATE"
                    token.value = owner.name
                    for _ in range(owner.prefix_count-1):
                        token.endlexpos = pending.popleft().endlexpos
            if (token.type in {"(", "{"} and self is _state.grammar and stack_prefix(parser, "DEFERRED_CTOR_ARGS") is not None
                    and any(hasattr(sym, "pending_bodies") for sym in parser.symstack)):
                previous = previous_value = ")" if token.type == "(" else "}"
                yield deferred_group(token, previous, "DEFERRED_CTOR_ARGS")
                continue
            if token.type == "{" and stack_prefix(parser, "HEAD_END") is not None:
                marker = copy(token)
                marker.type = "HEAD_END"
                yield marker
            if token.type == "(" and previous == "NOEXCEPT" and stack_prefix(parser, "(") is not None:
                previous, previous_value = token.type, token.value
                yield token
                continue
            new_type_prefix = stack_prefix(parser, "NEW_TYPE_OPEN") if token.type == "(" else None
            if new_type_prefix is not None and type_id_ahead(new_type_prefix, True):
                token.type = "NEW_TYPE_OPEN"
            type_id_prefix = stack_prefix(parser, "TYPE_PAREN") if token.type == "(" else None
            if type_id_prefix is not None and type_id_ahead(type_id_prefix, previous in {"SIZEOF", "ALIGNOF", "GNU_ALIGNOF", "GNU_TYPEOF", "TYPEID", "ALIGNAS"}, alignment=previous == "ALIGNAS"):
                token.type = "TYPE_PAREN"
            parameter_prefix = stack_prefix(parser, "PARAM_OPEN") if token.type == "(" else None
            if parameter_prefix is not None:
                parameter_scope = parser.symstack[:parameter_prefix]
                parameter_scope += [sym for sym in parser.symstack[parameter_prefix:] if sym.type in {"template_owner", "ctor_template_owner", "operator_owner", "overload_name", "declarator_id", "special_id"} and hasattr(sym, "namespace")]
                tail = parser.symstack[-3:]
                if [sym.type for sym in tail] == ["qualified_name", "SCOPE", "IDENT"]:
                    parameter_scope.append(SimpleNamespace(type="qualifier", namespace=self.namespace_path(parameter_scope, tail[0].value)))
            first = peek(0) if parameter_prefix is not None else None
            type_in_parentheses = (first is not None and (first.type in {"BUILTIN", "SPECIFIER", ")"} or (
                first.type == "IDENT" and self.lookup(parameter_scope, [first.value], False) in {"type", "type_template", "concept"})))
            starts_member_pointer = token.type == "(" and member_pointer(peek) is not None
            if token.type == "(" and (starts_member_pointer or not type_in_parentheses) and stack_prefix(parser, "GROUP_OPEN") is not None and (
                abstract_pointer_group() or (stack_prefix(parser, "(") is None and (
                    stack_prefix(parser, "PARAM_OPEN") is None or starts_member_pointer or peek(0) and peek(0).type in {"*", "&", "AND", "(", "["}
                )) or (
                    (close := grouped_name(0)) is not None and peek(close+1) is not None
                    and peek(close+1).type in {";", ",", "{", "[", "(", ")", "="}
                )
            ):
                token.type = "GROUP_OPEN"
            elif parameter_prefix is not None:
                direct_init = stack_prefix(parser, "INIT_OPEN") is not None
                expression = stack_prefix(parser, "(") is not None
                # T() can denote a function type in a template argument. A following
                # expression operator can instead require value initialization.
                empty_value = (expression and not direct_init and first and first.type == ")" and peek(1)
                               and peek(1).type in {"<", "+", "-", "/", "%", "EQ", "REL", "SPACESHIP",
                                                    "|", "^", "OR", "?", ".", "ARROW", "INC", "DEC"})
                if empty_value or (direct_init or expression) and not parameters_ahead(parameter_scope):
                    token.type = "INIT_OPEN" if direct_init else "("
                else:
                    token.type = "PARAM_OPEN"
                    token.locals = {}
                    token.using_namespaces = []
            elif token.type in {"FOR", "IF", "WHILE", "SWITCH", "DO"}:
                token.locals = {}
                token.using_namespaces = []
            elif token.type == "{" and stack_prefix(parser, "BLOCK_OPEN") is not None and (
                parser.symstack[-1].type != "HEAD_END" or parser.symstack[-2].value["type"] == "FunctionDeclaration"
            ):
                if self is _state.grammar and any(hasattr(sym, "pending_bodies") for sym in parser.symstack):
                    previous = previous_value = "}"
                    yield deferred_group(token, "}", "DEFERRED_BODY")
                    continue
                token.type = "BLOCK_OPEN"
                token.locals = {}
                token.using_namespaces = []
            if token.type == "ELLIPSIS" and (prefix := stack_prefix(parser, "PACK")) is not None:
                following = peek(0)
                # Without a name or suffix, an ellipsis can introduce C varargs.
                # Inspect only the symbols forming this parameter's type.
                parts = parser.symstack[prefix:]
                if not parts and parser.symstack[-1].type == "type":
                    parts = parser.symstack[-1:]
                pattern = [{"type": "TypeName", "name": sym.value} if sym.type == "TYPE_NAME" else sym.value
                           for sym in parts]
                if (following and following.type in {"IDENT", "[", "("}
                        or self.contains_pack(pattern, parser.symstack)):
                    token.type = "PACK"
            if (token.value in _FOLD_OPERATORS and stack_prefix(parser, "FOLD_OP") is not None
                    and (previous == "ELLIPSIS" or peek(0) and peek(0).type == "ELLIPSIS")):
                token.type = "FOLD_OP"
            if token.type == "TEMPLATE":
                token.template_types = set()
                token.template_names = set()
                token.template_values = set()
                token.template_packs = set()
            elif token.type == "<" and stack_prefix(parser, "OP_TEMPLATE_OPEN") is not None and self.operator_template_ahead(parser.symstack):
                token.type = "OP_TEMPLATE_OPEN"
                depth += 1
            elif token.type == "<" and stack_prefix(parser, "ANGLE_OPEN") is not None:
                token.type = "ANGLE_OPEN"
                depth += 1
            elif depth and token.value in {">", ">>"} and stack_prefix(parser, "ANGLE_CLOSE") is not None:
                if token.value == ">>":
                    rest = copy(token)
                    rest.type = rest.value = rest.spelling = ">"
                    rest.lexpos = token.endlexpos - 1
                    token.endlexpos = token.lexpos + 1
                    rest.lineno = bisect_right(self.source.lines, rest.lexpos)
                    pending.appendleft(rest)
                token.type, token.value = "ANGLE_CLOSE", ">"
                depth -= 1
            if (token.type == "IDENT" and previous == "~" and len(parser.symstack) >= 3
                    and getattr(parser.symstack[-2], "dependent_destructor", False)):
                token.type = "TYPE_NAME"
            if (token.type == "IDENT" and previous == "~" and len(parser.symstack) >= 4
                    and parser.symstack[-2].type in {".", "ARROW"} and stack_prefix(parser, "TYPE_NAME") is not None):
                receiver = self.receiver_binding(parser.symstack, parser.symstack[-3].value)
                if isinstance(receiver, tuple) and receiver[0] == "object":
                    if self.member_binding(receiver[1], token.value) in {"type", "type_template"}:
                        token.type = "TYPE_NAME"
            if token.type == "IDENT" and previous == "SCOPE" and peek(0) and peek(0).type == "<":
                if stack_prefix(parser, "MEMBER_TEMPLATE") is not None:
                    tail = parser.symstack
                    scope = None
                    if tail[-2].type == "qualified_name" and not self.has_dependent_qualifier(tail[:-2], tail[-2].value):
                        scope = self.namespace_path(tail[:-2], tail[-2].value)
                    elif [part.type for part in tail[-5:]] == [
                        "MEMBER_CLASS", "ANGLE_OPEN", "template_arguments_opt", "ANGLE_CLOSE", "SCOPE"
                    ]:
                        owner = {"name": tail[-5].value, "arguments": tail[-3].value}
                        scope = self.specialization_scope(tail[:-5], owner)
                    if scope is not None and self.member_binding(scope, token.value) in {"function_template", "variable_template"}:
                        token.type = "MEMBER_TEMPLATE"
            if token.type == "IDENT" and peek(0) and peek(0).type == ":" and stack_prefix(parser, "LABEL_NAME") is not None:
                token.type = "LABEL_NAME"
            if token.type == "IDENT" and peek(0) and peek(0).type == "(":
                prefix = stack_prefix(parser, "GUIDE_NAME")
                if prefix is not None:
                    scope = parser.symstack[:prefix]
                    path = (*self.namespace(scope), token.value)
                    if self.bindings.get(path) == "type_template" and path in self.class_scopes and guide_ahead():
                        token.type = "GUIDE_NAME"
            if previous != "SCOPE" and token.type in {"IDENT", "SCOPE"}:
                type_prefix = stack_prefix(parser, "TYPE_NAME")
                fn_prefix = stack_prefix(parser, "TEMPLATE_ID")
                template_prefix = stack_prefix(parser, "TEMPLATE_NAME")
                concept_prefix = stack_prefix(parser, "CONCEPT_NAME")
                member_prefix = stack_prefix(parser, "MEMBER_CLASS") if previous in {".", "ARROW"} else None
                if any(p is not None for p in (type_prefix, fn_prefix, template_prefix, concept_prefix, member_prefix)):
                    absolute = token.type == "SCOPE"
                    parts = [] if absolute else [token.value]
                    i = 0
                    if absolute and peek(i) and peek(i).type == "IDENT":
                        parts.append(peek(i).value)
                        i += 1
                    while peek(i) and peek(i).type == "SCOPE" and peek(i+1) and peek(i+1).type == "IDENT":
                        parts.append(peek(i+1).value)
                        i += 2
                    if self.using_namespaces and len(parts) > 1:
                        positions = [peek(0).lexpos if absolute else token.lexpos]
                        positions.extend(peek(j).lexpos for j in range(2 if absolute else 1, i, 2))
                        self.lookup_components = tuple(zip(parts, positions))
                    resolved = None
                    if member_prefix is not None and parts and peek(i) and peek(i).type == "<":
                        end = template_end(peek, i)
                        if (end is not None and peek(end+1) and peek(end+1).type == "SCOPE"
                                and self.lookup(parser.symstack[:member_prefix], parts, absolute) == "type_template"):
                            resolved = "MEMBER_CLASS"
                        elif len(parts) == 1 and not absolute and stack_prefix(parser, "MEMBER_TEMPLATE") is not None:
                            obj = self.receiver_binding(parser.symstack, parser.symstack[-2].value)
                            if isinstance(obj, tuple) and obj[0] == "object" and len(obj[2]) == (previous == "ARROW"):
                                if self.member_binding(obj[1], parts[0]) in {"function_template", "variable_template"}:
                                    resolved = "MEMBER_TEMPLATE"
                    if parts and peek(i) and peek(i).type == "<" and stack_prefix(parser, "CTOR_TEMPLATE") is not None:
                        if constructor_owner_ahead(i, parts[-1]):
                            resolved = "CTOR_TEMPLATE"
                    if concept_prefix is not None:
                        binding = self.lookup(parser.symstack[:concept_prefix], parts, absolute)
                        if isinstance(binding, tuple) and binding[0] == "concept":
                            resolved = "CONCEPT_NAME"
                            token.concept_info = binding
                    operator_scope = peek(i) and peek(i).type == "SCOPE" and peek(i+1) and peek(i+1).type in {"OPERATOR", "TEMPLATE"}
                    if template_prefix is not None and peek(i) and peek(i).value in {",", ">", ">>", "..."}:
                        if self.lookup(parser.symstack[:template_prefix], parts, absolute) == "type_template":
                            resolved = "TEMPLATE_NAME"
                    if not resolved and type_prefix is not None and not operator_scope:
                        scope = parser.symstack[:type_prefix]
                        if self.lookup(scope, parts, absolute) in {"type", "type_template"}:
                            resolved = "TYPE_NAME"
                        elif len(parts) > 1 and not absolute and in_cast_type(scope) and any(
                            parts[0] in getattr(sym, "template_types", ()) for sym in [*self.inherited_stack, *scope]
                        ):
                            resolved = "TYPE_NAME"
                            token.implicit_typename = True
                    if not resolved and fn_prefix is not None and peek(i) and peek(i).type == "<":
                        if self.lookup(parser.symstack[:fn_prefix], parts, absolute) in {"function_template", "variable_template"}:
                            resolved = "TEMPLATE_ID"
                    if resolved:
                        token.type = resolved
                        token.value = ("::" if absolute else "") + "::".join(parts)
                        for _ in range(i):
                            token.endlexpos = pending.popleft().endlexpos
            previous, previous_value = token.type, token.value
            yield token


class TypeIdGrammar(CppGrammar):
    start = "abstract_type"


class ParameterClauseGrammar(CppGrammar):
    start = "parameters_opt"


_state = local()
_build_lock = Lock()


class CppPipeline(CFamilyPipeline):
    source_suffixes = frozenset({".C", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx", ".cppm", ".ixx"})
    preprocessor = "g++"
    standard = "c++20"
    dialect = "c++"

    def tokenize(self, source):
        return [self.token_record(t) for t in CppSource(source).tokens()]

    def _parse(self, raw_source, collected):
        if not hasattr(_state, "grammar"):
            grammar = CppGrammar()
            _state.parameter_grammar = ParameterClauseGrammar()
            _state.type_grammar = TypeIdGrammar()
            _state.parameter_grammar.reset_names()
            _state.type_grammar.reset_names()
            with _build_lock:
                _state.parser = yacc.yacc(module=grammar, write_tables=False, debug=False)
                _state.type_parser = yacc.yacc(module=_state.type_grammar, write_tables=False, debug=False, errorlog=yacc.NullLogger())
                _state.parameter_parser = yacc.yacc(module=_state.parameter_grammar, write_tables=False, debug=False, errorlog=yacc.NullLogger())
            _state.grammar = grammar
        grammar, parser = _state.grammar, _state.parser
        grammar.reset_names()
        source = grammar.source = CppSource(raw_source)
        source.lexpos, source.lineno = 0, 1

        def raw():
            for t in source.tokens():
                if collected is not None:
                    collected.append(self.token_record(t))
                yield t

        tokens = grammar.parser_tokens(raw(), parser)

        def next_token():
            token = next(tokens, None)
            source.lexpos = token.lexpos if token else len(raw_source)
            source.lineno = token.lineno if token else len(source.lines)
            return token

        ast = parser.parse(lexer=source, tokenfunc=next_token, tracking=True)
        if grammar.pending_destructors:
            offset = min(pos for _, pos in grammar.pending_destructors.values())
            raise source.error(offset, "destructor member must be called")
        return ast
