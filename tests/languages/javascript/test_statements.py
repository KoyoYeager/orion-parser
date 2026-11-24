import json
import subprocess
import sys

import pytest

from orionparser.registry import get_pipeline


@pytest.mark.parametrize(("ext", "goal"), [("js", "script"), ("cjs", "script"), ("mjs", "module")])
def test_cli_nested_statements(tmp_path, ext, goal):
    path = tmp_path / f"sample.{ext}"
    path.write_text("#!orion\n;{ /* inside */ debugger; {} }", encoding="utf-8")
    output = subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"])
    assert json.loads(output) == {
        "type": "Program", "sourceType": goal,
        "body": [{"type": "EmptyStatement"}, {"type": "BlockStatement", "body": [
            {"type": "DebuggerStatement"}, {"type": "BlockStatement", "body": []},
        ]}],
    }


@pytest.mark.parametrize(("source", "location"), [
    ("{ /*\u2028*/", "line 2, column 3"), (";\r\n}", "line 2, column 1"),
    ("\u3000@", "line 1, column 2"), ("/* open", "line 1, column 1"),
])
def test_invalid_source(tmp_path, source, location):
    path = tmp_path / "sample.js"
    path.write_text(source, encoding="utf-8")
    result = get_pipeline(path).analyze_file(path)
    assert not result.success
    assert result.ast is None
    assert any(location in message for message in result.errors)


@pytest.mark.parametrize(("source", "count"), [
    ("debugger", 1), ("debugger/*\u2029*/debugger", 2), ("debugger\n;", 1),
])
def test_debugger_asi(tmp_path, source, count):
    pipeline = get_pipeline(tmp_path / "sample.js")
    assert pipeline.parse(source)["body"] == [{"type": "DebuggerStatement"}] * count


def test_asi_closing_brace(tmp_path):
    pipeline = get_pipeline(tmp_path / "sample.js")
    assert pipeline.parse("{debugger}")["body"][0]["body"] == [{"type": "DebuggerStatement"}]
    with pytest.raises(ValueError, match="line 1, column 10"):
        pipeline.parse("debugger debugger")


@pytest.mark.parametrize(("source", "param", "has_finally"), [
    ("try {} catch {}", None, False), ("try {} catch (err) {} finally {}", "err", True),
    ("try {} finally {}", None, True),
])
def test_try_statement(tmp_path, source, param, has_finally):
    node, = get_pipeline(tmp_path / "sample.js").parse(source)["body"]
    assert node["type"] == "TryStatement" and node["block"]["type"] == "BlockStatement"
    if "catch" in source:
        assert node["handler"]["type"] == "CatchClause"
        assert node["handler"]["param"] == ({"type": "Identifier", "name": param} if param else None)
    else:
        assert node["handler"] is None
    assert (node["finalizer"] is not None) == has_finally
