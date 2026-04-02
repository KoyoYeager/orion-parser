"""Accuracy tests — verify AST attributes, comment attachment, and analysis
results match expected values on hand-crafted code.

These tests go beyond "does it parse?" to verify that the output is
structurally correct: every node has the right type, line number,
children, and attached comments.
"""

import logging

from orionparser.languages.python.parser import parse_source
from orionparser.languages.python.preprocess import run_pipeline
from orionparser.languages.python.comment_attacher import attach_comments
from orionparser.analysis.symbols import extract_symbols
from orionparser.analysis.call_tree import extract_call_tree
from orionparser.analysis.data_flow import extract_data_flow
from orionparser.languages.python.pipeline import PythonPipeline

logging.disable(logging.WARNING)


def _full_parse(source: str) -> dict:
    """Parse with full pipeline (preprocessing + comment attachment)."""
    pipeline = PythonPipeline()
    from pathlib import Path
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(source)
        f.flush()
        result = pipeline.analyze_file(Path(f.name))
    assert result.success, f"Parse failed: {result.errors}"
    return result.ast


# ============================================================
# AST node attribute accuracy
# ============================================================


class TestFunctionDefAttributes:
    SOURCE = """\
def greet(name: str, times: int = 1) -> str:
    result = name * times
    return result
"""

    def test_node_type(self):
        ast = _full_parse(self.SOURCE)
        func = ast["body"][0]
        assert func["type"] == "FunctionDef"

    def test_name(self):
        ast = _full_parse(self.SOURCE)
        func = ast["body"][0]
        assert func["name"] == "greet"

    def test_line(self):
        ast = _full_parse(self.SOURCE)
        func = ast["body"][0]
        assert func["_line"] == 1

    def test_params(self):
        ast = _full_parse(self.SOURCE)
        func = ast["body"][0]
        params = func["params"]
        assert len(params) == 2
        assert params[0]["name"] == "name"
        assert params[0]["annotation"]["id"] == "str"
        assert params[1]["name"] == "times"
        assert params[1]["default"]["value"] == "1"

    def test_return_type(self):
        ast = _full_parse(self.SOURCE)
        func = ast["body"][0]
        assert func["returns"]["id"] == "str"

    def test_body_statements(self):
        ast = _full_parse(self.SOURCE)
        func = ast["body"][0]
        body = func["body"]
        assert len(body) == 2
        assert body[0]["type"] == "Assign"
        assert body[1]["type"] == "Return"


class TestClassDefAttributes:
    SOURCE = """\
class Vector(Base):
    dim: int = 2

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

    def length(self) -> float:
        return self.x
"""

    def test_node_type(self):
        ast = _full_parse(self.SOURCE)
        cls = ast["body"][0]
        assert cls["type"] == "ClassDef"

    def test_name_and_bases(self):
        ast = _full_parse(self.SOURCE)
        cls = ast["body"][0]
        assert cls["name"] == "Vector"
        assert len(cls["bases"]) == 1

    def test_class_body(self):
        ast = _full_parse(self.SOURCE)
        cls = ast["body"][0]
        body = cls["body"]
        # dim: int = 2, __init__, length
        assert len(body) == 3

    def test_method_names(self):
        ast = _full_parse(self.SOURCE)
        cls = ast["body"][0]
        methods = [n for n in cls["body"] if n["type"] == "FunctionDef"]
        names = [m["name"] for m in methods]
        assert names == ["__init__", "length"]


class TestControlFlowAttributes:
    SOURCE = """\
for i, val in enumerate(items):
    if val > threshold:
        results.append(val)
    elif val == 0:
        skipped += 1
    else:
        ignored += 1
"""

    def test_for_target(self):
        ast = _full_parse(self.SOURCE)
        for_stmt = ast["body"][0]
        assert for_stmt["type"] == "For"
        assert for_stmt["target"]["type"] == "Tuple"
        assert len(for_stmt["target"]["elts"]) == 2

    def test_if_elif_else(self):
        ast = _full_parse(self.SOURCE)
        for_stmt = ast["body"][0]
        if_stmt = for_stmt["body"][0]
        assert if_stmt["type"] == "If"
        assert if_stmt["test"]["type"] == "Compare"
        # elif is nested in orelse
        assert len(if_stmt["orelse"]) == 1
        elif_stmt = if_stmt["orelse"][0]
        assert elif_stmt["type"] == "If"
        # else
        assert len(elif_stmt["orelse"]) > 0


class TestImportAttributes:
    SOURCE = """\
import os
import sys as system
from pathlib import Path
from collections import defaultdict, OrderedDict
from . import utils
from ..core import Base
"""

    def test_import(self):
        ast = _full_parse(self.SOURCE)
        imp = ast["body"][0]
        assert imp["type"] == "Import"
        assert imp["names"][0]["name"] == "os"

    def test_import_as(self):
        ast = _full_parse(self.SOURCE)
        imp = ast["body"][1]
        assert imp["names"][0]["alias"] == "system"

    def test_from_import_multiple(self):
        ast = _full_parse(self.SOURCE)
        imp = ast["body"][3]
        assert imp["type"] == "ImportFrom"
        assert imp["module"] == "collections"
        names = [n["name"] for n in imp["names"]]
        assert names == ["defaultdict", "OrderedDict"]

    def test_relative_import(self):
        ast = _full_parse(self.SOURCE)
        imp = ast["body"][4]
        assert imp["module"] == "."
        assert imp["names"][0]["name"] == "utils"

    def test_double_dot_import(self):
        ast = _full_parse(self.SOURCE)
        imp = ast["body"][5]
        assert imp["module"] == "..core"


class TestExpressionAttributes:
    def test_list_comp(self):
        ast = _full_parse("[x * 2 for x in range(10) if x > 3]\n")
        expr = ast["body"][0]["value"]
        assert expr["type"] == "ListComp"
        assert len(expr["generators"]) == 1
        assert expr["generators"][0]["target"]["id"] == "x"

    def test_dict_comp(self):
        ast = _full_parse("{k: v for k, v in items.items()}\n")
        expr = ast["body"][0]["value"]
        assert expr["type"] == "DictComp"

    def test_ternary(self):
        ast = _full_parse("x = a if condition else b\n")
        assign = ast["body"][0]
        assert assign["value"]["type"] == "IfExp"
        assert assign["value"]["test"]["id"] == "condition"

    def test_lambda(self):
        ast = _full_parse("fn = lambda x, y: x + y\n")
        assign = ast["body"][0]
        lam = assign["value"]
        assert lam["type"] == "Lambda"
        assert len(lam["params"]) == 2

    def test_walrus(self):
        ast = _full_parse("if (n := len(items)) > 0:\n    pass\n")
        if_stmt = ast["body"][0]
        # The test in the if contains NamedExpr somewhere
        assert if_stmt["type"] == "If"

    def test_tuple_assign(self):
        ast = _full_parse("a, b, c = 1, 2, 3\n")
        assign = ast["body"][0]
        assert assign["target"]["type"] == "Tuple"
        assert len(assign["target"]["elts"]) == 3
        assert assign["value"]["type"] == "Tuple"


class TestMatchCaseAttributes:
    SOURCE = """\
match command:
    case "quit":
        exit()
    case str() as s if len(s) > 0:
        process(s)
    case _:
        pass
"""

    def test_match_node(self):
        ast = _full_parse(self.SOURCE)
        match = ast["body"][0]
        assert match["type"] == "Match"
        assert match["subject"]["id"] == "command"

    def test_case_count(self):
        ast = _full_parse(self.SOURCE)
        match = ast["body"][0]
        assert len(match["cases"]) == 3

    def test_wildcard_case(self):
        ast = _full_parse(self.SOURCE)
        match = ast["body"][0]
        wildcard = match["cases"][2]
        assert wildcard["pattern"]["id"] == "_"


class TestAsyncAttributes:
    SOURCE = """\
async def fetch(url: str) -> dict:
    async with session.get(url) as resp:
        data = await resp.json()
    return data
"""

    def test_async_def(self):
        ast = _full_parse(self.SOURCE)
        func = ast["body"][0]
        assert func["type"] == "AsyncFunctionDef"
        assert func["name"] == "fetch"
        assert func["returns"]["id"] == "dict"

    def test_async_with(self):
        ast = _full_parse(self.SOURCE)
        func = ast["body"][0]
        aw = func["body"][0]
        assert aw["type"] == "AsyncWith"


# ============================================================
# Comment attachment accuracy
# ============================================================


class TestCommentAttachmentAccuracy:
    def test_leading_comment_on_function(self):
        source = """\
# Calculate the sum of two numbers
def add(a, b):
    return a + b
"""
        ast = _full_parse(source)
        func = ast["body"][0]
        assert "comments" in func
        assert func["comments"][0]["position"] == "leading"
        assert "sum of two" in func["comments"][0]["text"]

    def test_inline_comment_on_assign(self):
        source = """\
x = 42  # the answer
y = 0
"""
        ast = _full_parse(source)
        assign = ast["body"][0]
        assert "comments" in assign
        assert assign["comments"][0]["position"] == "inline"
        assert "the answer" in assign["comments"][0]["text"]

    def test_no_comment_means_no_key(self):
        source = "x = 1\n"
        ast = _full_parse(source)
        assert "comments" not in ast["body"][0]

    def test_multiple_leading_comments(self):
        source = """\
# First line of docs
# Second line of docs
class MyClass:
    pass
"""
        ast = _full_parse(source)
        cls = ast["body"][0]
        assert "comments" in cls
        assert len(cls["comments"]) == 2
        assert cls["comments"][0]["line"] < cls["comments"][1]["line"]

    def test_comment_inside_class(self):
        source = """\
class Foo:
    # Method docs
    def bar(self):
        pass
"""
        ast = _full_parse(source)
        cls = ast["body"][0]
        method = cls["body"][0]
        assert "comments" in method
        assert "Method docs" in method["comments"][0]["text"]

    def test_comment_not_in_string(self):
        source = '''\
x = "# this is not a comment"
# this IS a comment
y = 1
'''
        ast = _full_parse(source)
        # x should NOT have a comment
        x_assign = ast["body"][0]
        assert "comments" not in x_assign
        # y SHOULD have the leading comment
        y_assign = ast["body"][1]
        assert "comments" in y_assign
        assert "this IS a comment" in y_assign["comments"][0]["text"]


# ============================================================
# Symbol extraction accuracy on real-looking code
# ============================================================


class TestSymbolAccuracyComplex:
    SOURCE = """\
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)
MAX_RETRY = 3

@dataclass
class Config:
    host: str = "localhost"
    port: int = 8080
    debug: bool = False

class Server:
    def __init__(self, config: Config):
        self.config = config
        self._running = False

    async def start(self):
        self._running = True
        logger.info("started")

    def stop(self):
        self._running = False

def create_server(host: str = "localhost") -> Server:
    cfg = Config(host=host)
    return Server(cfg)
"""

    def test_all_functions(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        st = extract_symbols(ast)
        assert st.function_names() == [
            "__init__", "start", "stop", "create_server"
        ]

    def test_all_classes(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        st = extract_symbols(ast)
        assert st.class_names() == ["Config", "Server"]

    def test_module_vars(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        st = extract_symbols(ast)
        assert st.variable_names(scope="<module>") == ["logger", "MAX_RETRY"]

    def test_instance_vars(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        st = extract_symbols(ast)
        init_vars = st.variable_names(scope="Server.__init__")
        assert "self.config" in init_vars
        assert "self._running" in init_vars

    def test_function_scope_vars(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        st = extract_symbols(ast)
        assert st.variable_names(scope="create_server") == ["cfg"]

    def test_imports(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        st = extract_symbols(ast)
        assert st.import_names() == ["logging", "Optional", "dataclass"]

    def test_method_scope(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        st = extract_symbols(ast)
        for sym in st.functions:
            if sym.name == "start":
                assert sym.scope == "Server"
            if sym.name == "create_server":
                assert sym.scope == "<module>"


# ============================================================
# Call tree accuracy
# ============================================================


class TestCallTreeAccuracy:
    SOURCE = """\
def validate(data):
    if not check_format(data):
        raise ValueError("bad format")
    return clean(data)

def process(items):
    for item in items:
        result = validate(item)
        save(result)

def main():
    data = load()
    process(data)
"""

    def test_functions(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        ct = extract_call_tree(ast)
        assert set(ct["functions"]) == {"validate", "process", "main"}

    def test_calls(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        ct = extract_call_tree(ast)
        calls = ct["calls"]
        assert ("validate", "check_format") in calls
        assert ("validate", "clean") in calls
        assert ("process", "validate") in calls
        assert ("process", "save") in calls
        assert ("main", "load") in calls
        assert ("main", "process") in calls

    def test_no_false_calls(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        ct = extract_call_tree(ast)
        callers = {c[0] for c in ct["calls"]}
        # main should not call validate directly
        main_callees = {c[1] for c in ct["calls"] if c[0] == "main"}
        assert "validate" not in main_callees


# ============================================================
# Data flow accuracy
# ============================================================


class TestDataFlowAccuracy:
    SOURCE = """\
x = 10
y = x + 1
z = y * x
"""

    def test_variable_definitions(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        df = extract_data_flow(ast)
        vars_defined = [k for k, v in df["variables"].items() if v["definitions"]]
        assert "<module>.x" in vars_defined
        assert "<module>.y" in vars_defined
        assert "<module>.z" in vars_defined

    def test_flow_x_to_y(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        df = extract_data_flow(ast)
        assert ("<module>.x", "<module>.y", "<module>") in df["flows"]

    def test_flow_y_to_z(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        df = extract_data_flow(ast)
        assert ("<module>.y", "<module>.z", "<module>") in df["flows"]

    def test_flow_x_to_z(self):
        preprocessed, _, _ = run_pipeline(self.SOURCE)
        ast = parse_source(preprocessed)
        df = extract_data_flow(ast)
        assert ("<module>.x", "<module>.z", "<module>") in df["flows"]


# ============================================================
# Docstring attachment accuracy
# ============================================================


class TestDocstringAttachment:
    def test_module_docstring(self):
        source = '"""Module docstring."""\nx = 1\n'
        ast = _full_parse(source)
        assert ast.get("docstring") == "Module docstring."

    def test_function_docstring(self):
        source = 'def f():\n    """Function docs."""\n    pass\n'
        ast = _full_parse(source)
        func = ast["body"][0]
        assert func.get("docstring") == "Function docs."

    def test_class_docstring(self):
        source = 'class Foo:\n    """Class docs."""\n    pass\n'
        ast = _full_parse(source)
        cls = ast["body"][0]
        assert cls.get("docstring") == "Class docs."

    def test_method_docstring(self):
        source = 'class Foo:\n    def bar(self):\n        """Bar method."""\n        pass\n'
        ast = _full_parse(source)
        method = ast["body"][0]["body"][0]
        assert method.get("docstring") == "Bar method."

    def test_multiline_docstring(self):
        source = 'def f():\n    """Line 1.\n\n    Line 2.\n    """\n    pass\n'
        ast = _full_parse(source)
        func = ast["body"][0]
        assert func.get("docstring") is not None
        assert "Line 1." in func["docstring"]
        assert "Line 2." in func["docstring"]

    def test_single_quote_docstring(self):
        source = "def f():\n    '''Single quote docs.'''\n    pass\n"
        ast = _full_parse(source)
        func = ast["body"][0]
        assert func.get("docstring") == "Single quote docs."

    def test_no_docstring(self):
        source = "def f():\n    x = 1\n"
        ast = _full_parse(source)
        func = ast["body"][0]
        assert func.get("docstring") is None

    def test_regular_string_not_docstring(self):
        source = 'def f():\n    x = "not a docstring"\n    pass\n'
        ast = _full_parse(source)
        func = ast["body"][0]
        assert func.get("docstring") is None

    def test_docstring_in_symbols(self):
        source = 'def greet(name):\n    """Say hello."""\n    return f"hi {name}"\n'
        ast = _full_parse(source)
        st = extract_symbols(ast)
        func = st.functions[0]
        assert func.name == "greet"
        assert func.docstring == "Say hello."

    def test_class_docstring_in_symbols(self):
        source = 'class MyAPI:\n    """REST API client."""\n    pass\n'
        ast = _full_parse(source)
        st = extract_symbols(ast)
        cls = st.classes[0]
        assert cls.name == "MyAPI"
        assert cls.docstring == "REST API client."

    def test_both_comments_and_docstring(self):
        source = '# Helper function\ndef helper():\n    """Do something useful."""\n    pass\n'
        ast = _full_parse(source)
        func = ast["body"][0]
        assert func.get("docstring") == "Do something useful."
        assert "comments" in func
        assert "Helper function" in func["comments"][0]["text"]
