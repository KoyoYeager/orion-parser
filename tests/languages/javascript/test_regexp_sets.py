import pytest

from orionparser.languages.javascript.pipeline import JavaScriptPipeline


def atoms(literal):
    expr = JavaScriptPipeline().parse(literal)["body"][0]["expression"]
    return expr["alternatives"][0]


def test_references_and_unicode_escapes():
    named, group, backref = atoms(r"/\k<letter>(?<letter>\u{10400})\1/u")
    assert named == {"type": "Backreference", "name": "letter"}
    assert group["name"] == "letter" and group["index"] == backref["index"] == 1
    assert group["alternatives"][0][0]["value"] == "𐐀"
    assert atoms(r"/\uD801\uDC00/u")[0]["value"] == "𐐀"
    high, repeated = atoms("/𐐀+/")
    assert ord(high["value"]) == 0xD801 and ord(repeated["atom"]["value"]) == 0xDC00


def test_unicode_properties_and_set_operations():
    expr, = atoms(r"/[[a-z]&&[\p{sc=Latn}--[xyz]]]/v")
    both = expr["expression"]
    assert both["type"] == "SetIntersection"
    assert both["left"]["expression"]["elements"][0]["type"] == "CharacterRange"
    diff = both["right"]["expression"]
    assert diff["type"] == "SetSubtraction"
    assert diff["left"]["name"] == "sc" and diff["left"]["value"] == "Latn"
    strings, = atoms(r"/[\q{ab|c|}\p{RGI_Emoji}]/v")
    a, b = strings["expression"]["elements"]
    assert a["alternatives"] == ["ab", "c", ""] and b["strings"]


@pytest.mark.parametrize("literal", [
    r"/\p{latin}/u", r"/\p{Script=latin}/u", r"/\P{RGI_Emoji}/v", r"/\p{RGI_Emoji}/u",
    r"/[^\q{ab}]/v", "/[a&&&]/v", "/[a--b&&c]/v", "/[a&&b-c]/v", r"/[\q{a||\d}]/v",
    r"/\k<absent>/u", r"/(?<x>a)(?<x>b)/u", r"/\2(a)/u",
])
def test_invalid_regexp(literal):
    with pytest.raises(ValueError, match="line 1, column"):
        atoms(literal)


def test_specification_count_limits():
    from orionparser.languages.javascript.pipeline import Grammar
    from orionparser.languages.javascript.regexp import check_capture_count
    from orionparser.languages.javascript.templates import check_template_size

    grammar = Grammar("")
    for guard, limit in [(check_capture_count, 2**32 - 1), (check_template_size, 2**32)]:
        guard(limit - 1, 0, grammar.error)
        with pytest.raises(ValueError, match="line 1, column 1"):
            guard(limit, 0, grammar.error)
