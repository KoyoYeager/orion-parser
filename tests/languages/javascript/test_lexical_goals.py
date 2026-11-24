import pytest

from orionparser.languages.javascript.pipeline import JavaScriptPipeline


def expression(source):
    return JavaScriptPipeline().parse(source)["body"][0]["expression"]


def test_template_interpolation():
    literal = expression("`a\r\n${{x: `b${c}`}.x}\\n${2}z`")
    assert [q["value"] for q in literal["quasis"]] == [
        {"raw": "a\n", "cooked": "a\n"}, {"raw": r"\n", "cooked": "\n"}, {"raw": "z", "cooked": "z"}]
    nested = literal["expressions"][0]["object"]["properties"][0]["value"]
    assert nested["expressions"][0]["name"] == "c" and nested["quasis"][-1]["tail"]
    assert literal["expressions"][1]["raw"] == "2"


def test_tagged_invalid_escape():
    tagged = expression(r"f()`\xZ${n}\u{}`")
    assert tagged["type"] == "TaggedTemplateExpression" and tagged["tag"]["type"] == "CallExpression"
    assert all(quasi["value"]["cooked"] is None for quasi in tagged["quasi"]["quasis"])
    with pytest.raises(ValueError):
        expression(r"`\xZ`")


def test_regexp_class_and_groups():
    pipeline = JavaScriptPipeline()
    source = r"if (a) /[a-z\d]+(?:b|c)*?\/$/giu.test(x); x /= a / b;"
    branch, division = pipeline.parse(source)["body"]
    regex = branch["consequent"]["expression"]["callee"]["object"]
    cls, group, slash, end = regex["alternatives"][0]
    assert cls["atom"]["elements"][0]["type"] == "CharacterRange" and cls["quantifier"] == "+"
    assert group["atom"]["kind"] == "(?:" and len(group["atom"]["alternatives"]) == 2
    assert not group["greedy"] and slash["value"] == "/" and end["kind"] == "$"
    assert regex["flags"] == "giu"
    assert division["expression"]["operator"] == "/=" and division["expression"]["right"]["operator"] == "/"
    kinds = [t["type"] for t in pipeline.tokenize(source)]
    assert kinds.count("REGEXP") == kinds.count("DIVIDE") == kinds.count("COMPOUND_ASSIGN") == 1


@pytest.mark.parametrize("source", ["/[z-a]/", "/(a/", "/+a/", "/a{3,2}/", "/x/gg", "/x/uv",
                                    "/a\nb/", r"/\a/u", "`x${}`", "`x${a`"])
def test_bad_literals(source):
    with pytest.raises(ValueError, match="line "):
        expression(source)


def test_class_elements():
    cls, = JavaScriptPipeline().parse("""class C extends Base {
      field = 0
      next
      constructor(x){this.x = x}
      static get count(){return 2}
      *[key](){yield 1}
      static { this.count }
    }""")["body"]
    assert cls["superClass"]["name"] == "Base"
    field, other, ctor, getter, generator, static_block = cls["body"]["body"]
    assert field["value"]["raw"] == "0" and other["value"] is None
    assert ctor["kind"] == "constructor" and not ctor["static"]
    assert getter["static"] and getter["kind"] == "get"
    assert generator["computed"] and generator["value"]["generator"]
    assert static_block["type"] == "StaticBlock"


@pytest.mark.parametrize("source", ["class C{ constructor(){} constructor(){} }", "class C{static prototype}",
                                    "class C{get constructor(){}}", "class C{static { return }}",
                                    "class C{m(){delete x}}", "class C{set x(){}}"])
def test_invalid_classes(source):
    with pytest.raises(ValueError):
        JavaScriptPipeline().parse(source)


def test_super_and_private_environments():
    cls, = JavaScriptPipeline().parse("""
        class C extends B {
            #token;
            constructor() { (() => super())() }
            check(x) {return class D {test(){return #token in x && x.#token}}}
            get value(){return super.value}
            field = new.target;
        }
    """)["body"]
    private, ctor, method, getter, field = cls["body"]["body"]
    assert private["key"] == {"type": "PrivateIdentifier", "name": "token"}
    assert ctor["value"]["body"]["body"][0]["expression"]["callee"]["body"]["callee"]["type"] == "Super"
    nested = method["value"]["body"]["body"][0]["argument"]
    logical = nested["body"]["body"][0]["value"]["body"]["body"][0]["argument"]
    assert logical["left"]["left"] == logical["right"]["property"] == private["key"]
    assert getter["kind"] == "get" and field["value"]["type"] == "MetaProperty"


@pytest.mark.parametrize("source", ["new.target", "class C{m(){super()}}", "obj.#x",
                                    "class C{#x;m(){delete this.#x}}", "class C{#a; static #a}",
                                    "class C{static get #a(){} set #a(x){}}",
                                    "class C extends B {constructor(){function f(){super()}}}"])
def test_invalid_lexical_context(source):
    with pytest.raises(ValueError):
        JavaScriptPipeline().parse(source)


@pytest.mark.parametrize("member", ["constructor(){}", "#private;"])
def test_duplicate_class_member_location(member):
    src = f"class C {{\n  {member}\n  {member}\n}}"
    with pytest.raises(ValueError, match=r"line 3, column 3: unexpected duplicate"):
        JavaScriptPipeline().parse(src)


def test_keyword_named_class_fields():
    cls, = JavaScriptPipeline().parse("class C {class; function = 1;}")["body"]
    a, b = cls["body"]["body"]
    assert a["key"]["name"] == "class" and b["key"]["name"] == "function"
    assert b["value"]["raw"] == "1"
