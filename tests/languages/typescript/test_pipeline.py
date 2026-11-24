import json
import subprocess
import sys

import pytest

from orionparser.languages.javascript.pipeline import SourceSyntaxError
from orionparser.registry import get_pipeline


@pytest.mark.parametrize(("suffix", "kind", "declaration"), [
    (".ts", "TS", False), (".tsx", "TSX", False), (".mts", "TS", False), (".cts", "TS", False),
    (".d.ts", "TS", True), (".d.mts", "TS", True), (".d.cts", "TS", True),
])
def test_alias_cli(tmp_path, suffix, kind, declaration):
    path = tmp_path / ("model" + suffix)
    path.write_text("export type Choice<T extends Root = Leaf> = Box<Inner<T>>[] | T & null;")
    command = [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]
    root = json.loads(subprocess.check_output(command))
    assert root["sourceType"] == "module" and root["scriptKind"] == kind and root["declarationFile"] == declaration
    alias = root["body"][0]["declaration"]
    assert alias["type"] == "TSTypeAliasDeclaration" and alias["id"]["name"] == "Choice"
    param, = alias["typeParameters"]["params"]
    assert param["constraint"]["typeName"]["name"] == "Root" and param["default"]["typeName"]["name"] == "Leaf"
    array, intersection = alias["typeAnnotation"]["types"]
    assert array["type"] == "TSArrayType"
    nested, = array["elementType"]["typeArguments"]["params"]
    assert nested["typeName"]["name"] == "Inner" and nested["typeArguments"]["params"][0]["typeName"]["name"] == "T"
    assert intersection["type"] == "TSIntersectionType"


def test_declarations_and_parameter_types(tmp_path):
    path = tmp_path / "lib.d.ts"
    path.write_text("""export interface Model<T> extends Root<T> {
        readonly value: T
        map<U>(input: T, option?: string): U;
    }
    export const model: Model<number>;
    declare const key: Model<string>['value'];""")
    result = get_pipeline(path).analyze_file(path)
    assert result.success, result.errors
    exported, const, ambient = result.ast["body"]
    interface = exported["declaration"]
    assert interface["id"]["name"] == "Model" and interface["extends"][0]["typeName"]["name"] == "Root"
    prop, method = interface["body"]["body"]
    assert prop["readonly"] and prop["key"]["name"] == "value"
    assert method["type"] == "TSMethodSignature" and method["params"][1]["optional"]
    assert method["returnType"]["typeAnnotation"]["typeName"]["name"] == "U"
    assert const["declaration"]["declarations"][0]["init"] is None
    assert ambient["declare"] and ambient["declarations"][0]["id"]["typeAnnotation"]["typeAnnotation"]["type"] == "TSIndexedAccessType"


def test_jsx_text_and_expressions(tmp_path):
    path = tmp_path / "ui.tsx"
    path.write_text("""export function view(name: string): Node {
      return <><UI.Label enabled title="a&amp;b" {...props}>Hi {name}</UI.Label>
        {ok && <ns:badge>{...children}</ns:badge>}</>
    }""")
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    func = ast["body"][0]["declaration"]
    assert func["params"][0]["typeAnnotation"]["typeAnnotation"] == {"type": "TSStringKeyword"}
    fragment = func["body"]["body"][0]["argument"]
    element, whitespace, cond = fragment["children"]
    assert whitespace["value"].strip() == ""
    opening = element["openingElement"]
    assert opening["name"]["property"]["name"] == "Label"
    assert opening["attributes"][1]["value"]["value"] == "a&amp;b"
    assert opening["attributes"][2]["argument"]["name"] == "props"
    assert element["children"][1]["expression"]["name"] == "name"
    badge = cond["expression"]["right"]
    assert badge["closingElement"]["name"]["namespace"]["name"] == "ns"
    assert badge["children"][0]["type"] == "JSXSpreadChild"


def test_nested_lexical_modes(tmp_path):
    ast = get_pipeline(tmp_path / "nested.tsx").parse("async function f(){return `A${<await>{await x}</await>}Z`}")
    template = ast["body"][0]["body"]["body"][0]["argument"]
    assert template["quasis"][-1]["value"]["raw"] == "Z"
    assert template["expressions"][0]["children"][0]["expression"]["type"] == "AwaitExpression"


def test_line_break_and_value_shift(tmp_path):
    tree = get_pipeline(tmp_path / "f.ts").parse("type A=number\n[]; let x:Box<Box<A>>=y; x >>= 1")
    alias, empty_array, var, shift = tree["body"]
    assert alias["typeAnnotation"]["type"] == "TSNumberKeyword"
    assert empty_array["expression"]["type"] == "ArrayExpression"
    assert var["declarations"][0]["init"]["name"] == "y" and shift["expression"]["operator"] == ">>="


@pytest.mark.parametrize(("name", "source"), [
    ("bad.ts", "type A = X<Y;"), ("bad.tsx", "const x=<A></B>"), ("bad.ts", "const x=<A/>"),
    ("bad.tsx", "const x=<A>bad > text</A>"), ("bad.ts", "type A = (string | );"),
    ("bad.mjs", "type A = number;"),
])
def test_positioned_rejections(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source)
    result = get_pipeline(path).analyze_file(path)
    assert not result.success and result.ast is None
    assert any("line 1, column " in error for error in result.errors)


def test_external_module_and_qualified_namespace(tmp_path):
    path = tmp_path / "server.d.cts"
    path.write_text("""import lib = require('lib');
    declare namespace Server.API { export interface Client { value: string } }
    declare module 'extras' { export const defaultValue: string; }
    export = lib;""")
    result = get_pipeline(path).analyze_file(path)
    assert result.success, result.errors
    imported, namespace, ambient, exported = result.ast["body"]
    assert imported["moduleReference"]["expression"]["value"] == "lib"
    assert namespace["declare"] and namespace["id"]["name"] == "Server"
    api = namespace["body"]
    assert api["id"]["name"] == "API" and api["body"]["body"][0]["declaration"]["id"]["name"] == "Client"
    assert ambient["id"]["value"] == "extras" and ambient["body"]["body"][0]["declaration"]["kind"] == "const"
    assert exported["expression"]["name"] == "lib"


def test_signatures_tuples_and_templates(tmp_path):
    path = tmp_path / "sigs.ts"
    root = get_pipeline(path).parse("""
    type Fn<T> = (x:T) => T | null;
    type Tag<T> = `key:${T}`;
    type Tuple = [string?, count?: number];
    enum Mode { Off, On = 2 }
    declare function make<T>(x:T): Fn<T>;
    class Impl<T> implements Model<T> { value: T; [key:string]: T }
    """)
    fn, tag, pair, enum, signature, cls = root["body"]
    assert fn["typeAnnotation"]["returnType"]["type"] == "TSUnionType"
    assert fn["typeAnnotation"]["params"][0]["name"] == "x"
    assert tag["typeAnnotation"]["types"][0]["typeName"]["name"] == "T"
    first, second = pair["typeAnnotation"]["elementTypes"]
    assert first["type"] == "TSOptionalType" and second["optional"] and second["label"]["name"] == "count"
    assert enum["members"][1]["initializer"]["raw"] == "2" and signature["declare"]
    assert cls["implements"][0]["typeName"]["name"] == "Model"
    assert cls["body"]["body"][1]["type"] == "TSIndexSignature"


def test_speculative_calls_preserve_comparisons(tmp_path):
    pipeline = get_pipeline(tmp_path / "expr.ts")
    call, comparison, instantiation = [s["expression"] for s in pipeline.parse(
        "f<Map<X,Y>>(x); a < b + c > (x); f<T>;"
    )["body"]]
    assert call["type"] == "CallExpression" and call["callee"]["name"] == "f"
    outer = call["typeArguments"]["params"][0]
    assert outer["typeName"]["name"] == "Map" and len(outer["typeArguments"]["params"]) == 2
    assert comparison["operator"] == ">" and comparison["left"]["operator"] == "<"
    assert comparison["left"]["right"]["operator"] == "+"
    assert instantiation["type"] == "TSInstantiationExpression"


def test_typed_arrows_assertions_and_jsx_arguments(tmp_path):
    path = tmp_path / "render.tsx"
    program = get_pipeline(path).parse("""
    const view = <UI.View<Box<T>> render={(x: T) => x as T | null} />;
    const callback = async(x?: T) => (await x) satisfies T;
    """)
    opening = program["body"][0]["declarations"][0]["init"]["openingElement"]
    assert opening["typeArguments"]["params"][0]["typeName"]["name"] == "Box"
    arrow = opening["attributes"][0]["value"]["expression"]
    assert arrow["params"][0]["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "T"
    assert arrow["body"]["type"] == "TSAsExpression" and arrow["body"]["typeAnnotation"]["type"] == "TSUnionType"
    callback = program["body"][1]["declarations"][0]["init"]
    assert callback["params"][0]["optional"] and callback["body"]["type"] == "TSSatisfiesExpression"
    assert callback["body"]["expression"]["type"] == "AwaitExpression"


def test_reject_type_annotation_in_an_ordinary_call(tmp_path):
    with pytest.raises(ValueError, match="type annotation outside arrow parameters"):
        get_pipeline(tmp_path / "invalid.ts").parse("fn(x: T)")


def test_mapped_and_conditional_types(tmp_path):
    source = "type Pick<T> = {-readonly [K in keyof T as K]-?: T[K] extends Box<infer U> ? U : never};"
    alias = get_pipeline(tmp_path / "m.ts").parse(source)["body"][0]
    mapped = alias["typeAnnotation"]
    assert mapped["type"] == "TSMappedType" and mapped["readonly"] == mapped["optional"] == "-"
    assert mapped["key"]["name"] == "K" and mapped["constraint"]["operator"] == "keyof"
    check = mapped["typeAnnotation"]
    assert check["type"] == "TSConditionalType" and check["checkType"]["type"] == "TSIndexedAccessType"
    assert check["extendsType"]["typeArguments"]["params"][0]["type"] == "TSInferType"
    assert check["falseType"]["type"] == "TSNeverKeyword"


def test_declaration_merging_and_parameter_property(tmp_path):
    source = """export declare function lib(): string;
    export declare namespace lib { export const version: string; }
    class Component { constructor(public readonly props: lib.Property) {} }
    """
    sig, ns, cls = get_pipeline(tmp_path / "c.ts").parse(source)["body"]
    assert sig["declaration"]["id"] == ns["declaration"]["id"]
    param, = cls["body"]["body"][0]["value"]["params"]
    assert param["parameterProperty"] and param["accessibility"] == "public" and param["readonly"]


def test_jsx_namespace_cannot_be_member_base(tmp_path):
    with pytest.raises(ValueError, match="namespaced JSX tag"):
        get_pipeline(tmp_path / "bad.tsx").parse("<a:b.c></a:b.c>")


def test_type_predicate_and_non_null(tmp_path):
    src = """declare function ensure(x: unknown): asserts x is string;
    function has(this: Box, x: unknown): x is number {return typeof x === "number"}
    const value = box!.item! as const;"""
    ensure, has, var = get_pipeline(tmp_path / "narrow.ts").parse(src)["body"]
    assert ensure["returnType"]["typeAnnotation"]["asserts"]
    predicate = has["returnType"]["typeAnnotation"]
    assert not predicate["asserts"] and predicate["parameterName"]["name"] == "x"
    assert has["params"][0]["name"] == "this" and predicate["typeAnnotation"]["typeAnnotation"]["type"] == "TSNumberKeyword"
    assertion = var["declarations"][0]["init"]
    assert assertion["typeAnnotation"]["typeName"]["name"] == "const"
    assert assertion["expression"]["expression"]["object"]["type"] == "TSNonNullExpression"


def test_return_annotations_and_conditional_separator(tmp_path):
    tree = get_pipeline(tmp_path / "arrows.ts").parse("""
        const project = ([key]): Key => key;
        const run = async(x:T):Promise<T>=>await x;
        const choose = flag ? (x) : y => y;
    """)
    project, run, choice = [stmt["declarations"][0]["init"] for stmt in tree["body"]]
    assert project["params"][0]["type"] == "ArrayPattern"
    assert project["returnType"]["typeAnnotation"]["typeName"]["name"] == "Key"
    assert run["async"] and run["body"]["type"] == "AwaitExpression"
    assert run["returnType"]["typeAnnotation"]["typeArguments"]["params"][0]["typeName"]["name"] == "T"
    assert choice["type"] == "ConditionalExpression" and choice["alternate"]["type"] == "ArrowFunctionExpression"


def test_import_types_and_definite_assignment(tmp_path):
    tree = get_pipeline(tmp_path / "imports.ts").parse("""
        let value!: import('pkg').Nested.Item<T>;
        type Module = typeof import('pkg');
        type Sentinel = -1;
        (target.field as T) = value;
    """)
    var, module, sentinel, assignment = tree["body"]
    decl = var["declarations"][0]
    typ = decl["id"]["typeAnnotation"]["typeAnnotation"]
    assert decl["definite"] and decl["init"] is None
    assert typ["qualifier"]["right"]["name"] == "Item" and typ["typeArguments"]["params"][0]["typeName"]["name"] == "T"
    assert module["typeAnnotation"]["exprName"]["argument"]["value"] == "pkg"
    assert sentinel["typeAnnotation"]["literal"]["argument"]["raw"] == "1"
    assert assignment["expression"]["left"]["type"] == "TSAsExpression"


def test_types_in_scopes_and_members(tmp_path):
    source = """
    import {type Item, type as value} from "pkg";
    const Item = 0;
    export type Kind = number;
    export const Kind = 1;
    let label: string;
    namespace Inner {var label: string}
    interface Pair<in out T> {}
    class C { static readonly n: number = 1; constructor(x: number); constructor(x: number) {} }
    function* values<T>(x:T){yield x}
    const obj = {read<T>(x:T){return x}};
    const f = ({key}: Item) => key;
    """
    nodes = get_pipeline(tmp_path / "scope.ts").parse(source)["body"]
    first, second = nodes[0]["specifiers"]
    assert first["importKind"] == "type" and second["local"]["name"] == "value"
    param, = nodes[6]["typeParameters"]["params"]
    assert param["in"] and param["out"]
    field, sig, implementation = nodes[7]["body"]["body"]
    assert field["readonly"] and field["static"] and sig["value"]["body"] is None
    assert implementation["value"]["body"]["type"] == "BlockStatement"
    assert nodes[8]["generator"] and nodes[8]["typeParameters"]["params"][0]["name"]["name"] == "T"
    assert nodes[9]["declarations"][0]["init"]["properties"][0]["value"]["typeParameters"]
    binding = nodes[10]["declarations"][0]["init"]["params"][0]
    assert binding["type"] == "ObjectPattern" and binding["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "Item"


def test_generic_arrow_and_angle_assertion_goals(tmp_path):
    for name, arrow in [("a.ts", "<T>(x:T)=>x"), ("b.tsx", "<T,>(x:T):T=>x"),
                        ("c.tsx", "<T extends Item>(x:T)=>x")]:
        node = get_pipeline(tmp_path / name).parse(arrow)["body"][0]["expression"]
        assert node["type"] == "ArrowFunctionExpression"
        assert node["typeParameters"]["params"][0]["name"]["name"] == "T"
        assert node["params"][0]["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "T"
    assertion = get_pipeline(tmp_path / "a.ts").parse("<T>(x)")["body"][0]["expression"]
    assert assertion["type"] == "TSTypeAssertion" and assertion["expression"]["name"] == "x"
    tsx = get_pipeline(tmp_path / "b.tsx")
    assert tsx.parse("<T>𐐀</T>")["body"][0]["expression"]["children"][0]["value"] == "𐐀"
    with pytest.raises(ValueError):
        tsx.parse("<T>(x:T)=>x")


def test_typed_return_inside_call(tmp_path):
    src = "register(([x]: [T]): x is Valid => true); register(flag ? (x) : y => y)"
    a, b = get_pipeline(tmp_path / "a.ts").parse(src)["body"]
    callback = a["expression"]["arguments"][0]
    assert callback["returnType"]["typeAnnotation"]["type"] == "TSTypePredicate"
    assert callback["params"][0]["typeAnnotation"]["typeAnnotation"]["type"] == "TSTupleType"
    assert b["expression"]["arguments"][0]["type"] == "ConditionalExpression"


def test_index_signature_and_super_in_same_class(tmp_path):
    cls, = get_pipeline(tmp_path / "c.ts").parse("class D extends B { [key: string]: T; constructor(){ super() } }")["body"]
    index, ctor = cls["body"]["body"]
    assert index["type"] == "TSIndexSignature" and ctor["value"]["body"]["body"][0]["expression"]["callee"]["type"] == "Super"


def test_decorators_in_classes_and_parameters(tmp_path):
    src = """
    @outer @registry.tag('meta') export class C {
        @field accessor value = 1;
        @method [key](@arg input: T) {}
    }
    const Local = @outer class {};
    """
    cls, local = get_pipeline(tmp_path / "dec.ts").parse(src)["body"]
    decl = cls["declaration"]
    outer, inner = decl["decorators"]
    assert outer["expression"]["name"] == "outer"
    assert inner["expression"]["callee"]["property"]["name"] == "tag"
    field, method = decl["body"]["body"]
    assert field["accessor"] and field["decorators"][0]["expression"]["name"] == "field"
    assert method["computed"] and method["decorators"][0]["expression"]["name"] == "method"
    assert method["value"]["params"][0]["decorators"][0]["expression"]["name"] == "arg"
    assert local["declarations"][0]["init"]["decorators"][0]["expression"]["name"] == "outer"


def test_using_and_type_only_exports(tmp_path):
    src = """
    export default abstract class Service{}
    type T = Value; export type { T as V };
    export type * as Public from 'other';
    export {type T as Annot};
    async function run(){ await using res = acquire(); for(using x of xs) consume(x); }
    """
    cls, _, named, star, spec, function = get_pipeline(tmp_path / "x.ts").parse(src)["body"]
    assert cls["declaration"]["abstract"]
    assert named["exportKind"] == star["exportKind"] == "type" and star["exported"]["name"] == "Public"
    assert spec["specifiers"][0]["exportKind"] == "type"
    decl, loop = function["body"]["body"]
    assert decl["kind"] == "await using" and loop["left"]["kind"] == "using"


@pytest.mark.parametrize("source", ["using x = ;", "using {x:} = o;", "for(using x in );"])
def test_invalid_using(tmp_path, source):
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "x.ts").parse(source)


def test_conditional_with_typed_arrow_arm(tmp_path):
    pipeline = get_pipeline(tmp_path / "f.ts")
    for source in ["flag ? (x): T => x : other", "flag ? (): T => x : other",
                   "flag ? (x:T): T => x : other"]:
        expr = pipeline.parse(source)["body"][0]["expression"]
        assert expr["consequent"]["returnType"]["typeAnnotation"]["typeName"]["name"] == "T"
        assert expr["alternate"]["name"] == "other"
    expr = pipeline.parse("flag ? (x) : T => x")["body"][0]["expression"]
    assert expr["consequent"]["name"] == "x" and expr["alternate"]["type"] == "ArrowFunctionExpression"


@pytest.mark.parametrize("source", [
    "class C{f(@dec this:T){}}", "class C{public @dec m(){}}", "010",
    "class C{#x; f(o:C){return o?.value.#x}}", "fn<T>.property", "for(using of of []);",
    '/// <reference types="pkg" resolution-mode="esm"/>\nexport {}',
])
def test_typescript_specific_parse_errors(tmp_path, source):
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "errors.ts").parse(source)


def test_reference_modes_and_grouped_instantiation(tmp_path):
    source = """/// <reference types="pkg" resolution-mode="require" preserve="true" />
    (fn<T>).property;
    /// <reference types="invalid" resolution-mode="bad" />
    """
    result = get_pipeline(tmp_path / "ok.ts").parse(source)
    assert result["references"] == [{"kind": "types", "value": "pkg", "resolutionMode": "require", "preserve": True}]
    assert result["body"][0]["expression"]["object"]["type"] == "TSInstantiationExpression"


def test_marked_members_and_accessor_signatures(tmp_path):
    source = """
    declare abstract class C {
      abstract get size(): number;
      static set flag(value: boolean);
      field?;
      static maybe?<T>(x:T):T;
      generic<T>(x:T):T {return x}
    }
    """
    cls, = get_pipeline(tmp_path / "sigs.d.ts").parse(source)["body"]
    get, set_, field, optional, generic = cls["body"]["body"]
    assert get["kind"] == "get" and get["abstract"] and get["value"]["body"] is None
    assert set_["static"] and set_["kind"] == "set" and len(set_["value"]["params"]) == 1
    assert field["optional"] and field["typeAnnotation"] is None
    assert optional["optional"] and optional["static"] and optional["value"]["typeParameters"]
    assert generic["value"]["body"]["body"][0]["argument"]["name"] == "x"


def test_import_phases_and_attributes(tmp_path):
    source = """
    import data from 'a' with {type:'json'};
    import defer * as ns from 'b';
    export type * from 'c' with {'resolution-mode':'require'};
    type Alias=import('d',{with:{'resolution-mode':'import'}}).Entry<T>;
    const promise = import.defer('b');
    const json = import('a', {with:{type:'json'}});
    """
    static, deferred, reexport, alias, promise, dynamic = get_pipeline(tmp_path / "imports.mts").parse(source)["body"]
    assert static["attributes"][0]["key"]["name"] == "type" and static["attributeKeyword"] == "with"
    assert deferred["phase"] == "defer" and deferred["specifiers"][0]["local"]["name"] == "ns"
    assert reexport["exportKind"] == "type" and reexport["attributes"][0]["value"]["value"] == "require"
    assert alias["typeAnnotation"]["attributes"][0]["key"]["value"] == "resolution-mode"
    assert alias["typeAnnotation"]["qualifier"]["name"] == "Entry"
    assert promise["declarations"][0]["init"]["phase"] == "defer"
    assert dynamic["declarations"][0]["init"]["options"]["type"] == "ObjectExpression"


def test_generic_async_functions_and_methods(tmp_path):
    pipeline = get_pipeline(tmp_path / "async.mts")
    body = pipeline.parse("""
    export default async function*<T>(values:T[]){yield await values[0]}
    const fn = async function named<T>(x:T):Promise<T>{return await x};
    const obj = {async m<T>(x:T){return await x}};
    class C {static async *m<T>(x:T){yield await x}}
    """)["body"]
    default, fn, obj, cls = body
    methods = [default["declaration"], fn["declarations"][0]["init"],
               obj["declarations"][0]["init"]["properties"][0]["value"], cls["body"]["body"][0]["value"]]
    assert all(f["async"] and f["typeParameters"]["params"][0]["name"]["name"] == "T" for f in methods)
    assert [f["generator"] for f in methods] == [True, False, False, True]
    assert methods[0]["body"]["body"][0]["expression"]["argument"]["type"] == "AwaitExpression"
    assert methods[1]["returnType"]["typeAnnotation"]["typeName"]["name"] == "Promise"


def test_static_index_signature_and_query_types(tmp_path):
    src = "class C extends mix<T>() {static readonly [key:string]: number} type Q=typeof this.field; type G=typeof f<T>"
    cls, query, generic = get_pipeline(tmp_path / "types.ts").parse(src)["body"]
    assert cls["superClass"]["callee"]["name"] == "mix"
    assert cls["superClass"]["typeArguments"]["params"][0]["typeName"]["name"] == "T"
    index, = cls["body"]["body"]
    assert index["type"] == "TSIndexSignature" and index["static"] and index["readonly"]
    assert query["typeAnnotation"]["exprName"]["left"]["type"] == "TSThisType"
    assert generic["typeAnnotation"]["typeArguments"]["params"][0]["typeName"]["name"] == "T"


def test_library_declaration_forms(tmp_path):
    src = """interface Descriptor<T>{
      get size(): number;
      set size(x:number);
      get?(value:T): void;
      readonly [index:number]: T;
    }
    type Receiver<T> = T extends (this: infer U, ...args: never) => any ? U : unknown;
    """
    iface, receiver = get_pipeline(tmp_path / "lib.d.ts").parse(src)["body"]
    getter, setter, optional, index = iface["body"]["body"]
    assert getter["kind"] == "get" and setter["kind"] == "set"
    assert optional["key"]["name"] == "get" and optional["optional"]
    assert index["readonly"] and index["type"] == "TSIndexSignature"
    bound = receiver["typeAnnotation"]["extendsType"]
    assert bound["type"] == "TSFunctionType" and bound["params"][0]["name"] == "this"
    assert bound["params"][0]["typeAnnotation"]["typeAnnotation"]["type"] == "TSInferType"


def test_const_parameters_and_async_generic_arrow(tmp_path):
    src = "function f<const T extends X>(x:T){return x}; const g=async<const U,>(x:U):Promise<U>=>await x"
    for name in ["const.ts", "const.tsx"]:
        f, _, var = get_pipeline(tmp_path / name).parse(src)["body"]
        assert f["typeParameters"]["params"][0]["const"]
        g = var["declarations"][0]["init"]
        assert g["async"] and g["typeParameters"]["params"][0]["const"]
        assert g["returnType"]["typeAnnotation"]["typeArguments"]["params"][0]["typeName"]["name"] == "U"
        assert g["body"]["type"] == "AwaitExpression"
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "ambiguous.tsx").parse("const f=<const T>(x:T)=>x")
    assertion = get_pipeline(tmp_path / "ok.ts").parse("<const>{x:1}")["body"][0]["expression"]
    assert assertion["typeAnnotation"]["typeName"]["name"] == "const"


def test_type_reference_names_in_async_and_generator_contexts(tmp_path):
    tree = get_pipeline(tmp_path / "ctx.ts").parse(
        "async function read(){let x:await}; function* generate(){let x:yield}; type Alias=default"
    )
    for index, name in [(0, "await"), (2, "yield")]:
        var = tree["body"][index]["body"]["body"][0]["declarations"][0]
        assert var["id"]["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == name
    assert tree["body"][-1]["typeAnnotation"]["typeName"]["name"] == "default"
    func, = get_pipeline(tmp_path / "ctx.ts").parse("async function read(){let await=1}")["body"]
    binding, = func["body"]["body"][0]["declarations"]
    assert binding["id"]["name"] == "await" and binding["init"]["raw"] == "1"


def test_constrained_infer_and_conditional_boundaries(tmp_path):
    src = """
    type Nested<T> = T extends [infer X extends A | B & C] ? X : never;
    type Conditional = infer X extends A ? B : C;
    type ExtractNum<T> = T extends `${infer N extends number}` ? N : never;
    """
    nested, conditional, template = get_pipeline(tmp_path / "infer.ts").parse(src)["body"]
    constraint = nested["typeAnnotation"]["extendsType"]["elementTypes"][0]["typeParameter"]["constraint"]
    assert constraint["type"] == "TSUnionType" and constraint["types"][1]["type"] == "TSIntersectionType"
    assert "constraint" not in conditional["typeAnnotation"]["checkType"]["typeParameter"]
    inferred, = template["typeAnnotation"]["extendsType"]["types"]
    assert inferred["typeParameter"]["constraint"]["type"] == "TSNumberKeyword"


def test_unannotated_calls_and_default_interfaces(tmp_path):
    parser = get_pipeline(tmp_path / "iface.d.ts")
    src = "export default interface I { (x: T); <U>(x:U); }"
    iface = parser.parse(src)["body"][0]["declaration"]
    assert iface["type"] == "TSInterfaceDeclaration" and iface["id"]["name"] == "I"
    for source, offset, length in [("export default interface {}", 25, 1), ("export default interface  ", 24, 0)]:
        with pytest.raises(ValueError) as failure:
            parser.parse(source)
        assert (failure.value.code, failure.value.offset, failure.value.length) == (1003, offset, length)
    first, second = iface["body"]["body"]
    assert first["returnType"] is None and second["typeParameters"]["params"][0]["name"]["name"] == "U"


def test_contextual_words_and_switch_labels(tmp_path):
    src = "let as=1; switch(x){case (<T>() => x)(): ;} for(using of = null;;) break;"
    bind, switch, loop = get_pipeline(tmp_path / "x.ts").parse(src)["body"]
    assert bind["declarations"][0]["id"]["name"] == "as"
    assert switch["cases"][0]["test"]["callee"]["typeParameters"]["params"][0]["name"]["name"] == "T"
    assert loop["init"]["kind"] == "using" and loop["init"]["declarations"][0]["id"]["name"] == "of"


def test_optional_binding_patterns_in_signatures(tmp_path):
    pipeline = get_pipeline(tmp_path / "optional.ts")
    sig, fn = pipeline.parse("function f({a}?: A, [b]?: B); function f(...args:any[]){}")["body"]
    obj, arr = sig["params"]
    assert obj["type"] == "ObjectPattern" and obj["optional"] and obj["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "A"
    assert arr["type"] == "ArrayPattern" and arr["optional"]
    assert fn["params"][0]["type"] == "RestElement"
    assert "diagnostics" not in obj and "diagnostics" not in arr
    for src, pattern in [("function f({a}?:A){}", "{a}"), ("([x]?:T)=>x", "[x]"),
                         ("({x}?:T)=>{return x}", "{x}")]:
        statement, = pipeline.parse(src)["body"]
        parameter, = statement.get("expression", statement)["params"]
        assert parameter["type"] in {"ArrayPattern", "ObjectPattern"} and parameter["optional"]
        diagnostic, = parameter["diagnostics"]
        assert (diagnostic["code"], diagnostic["offset"]) == (2463, src.index(pattern))


def test_typed_catch_binding(tmp_path):
    tree = get_pipeline(tmp_path / "catch.ts").parse("try{}catch(error:unknown){throw error}")
    param = tree["body"][0]["handler"]["param"]
    assert param["name"] == "error" and param["typeAnnotation"]["typeAnnotation"]["type"] == "TSUnknownKeyword"


def test_catch_initializer_tree(tmp_path):
    src = "try{} catch ({p: x} = /*𐐀*/ make(1)) {} finally {}"
    stmt, = get_pipeline(tmp_path / "caught.ts").parse(src)["body"]
    catch = stmt["handler"]
    assert stmt["finalizer"]["type"] == "BlockStatement"
    prop, = catch["param"]["properties"]
    assert prop["key"]["name"] == "p" and prop["value"]["name"] == "x"
    initializer = catch["initializer"]
    assert initializer["type"] == "CallExpression" and initializer["callee"]["name"] == "make"
    assert initializer["arguments"][0]["raw"] == "1"
    diagnostic, = catch["diagnostics"]
    assert (diagnostic["code"], diagnostic["offset"]) == (1197, src.index("make"))
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "caught.js").parse(src)


def test_default_export_overloads(tmp_path):
    pipeline = get_pipeline(tmp_path / "overloads.ts")
    items = pipeline.parse("""
        export default function parse<T>(x:T): T;
        export default function parse<T>(x:T): T { return x }
    """)["body"]
    sig, fn = [item["declaration"] for item in items]
    assert sig["type"] == "TSDeclareFunction" and fn["type"] == "FunctionDeclaration"
    for node in (sig, fn):
        assert node["id"]["name"] == "parse" and node["typeParameters"]["params"][0]["name"]["name"] == "T"
        assert node["returnType"]["typeAnnotation"]["typeName"]["name"] == "T"
    anon = pipeline.parse("export default function<T>(x:T):T;")["body"][0]["declaration"]
    assert anon["id"] is None and anon["params"][0]["name"] == "x"


def test_default_export_type_and_value_spaces(tmp_path):
    pipeline = get_pipeline(tmp_path / "spaces.ts")
    merged = pipeline.parse("export * as X from 'm'; export type X<T> = T;")
    assert merged["body"][0]["exported"]["name"] == merged["body"][1]["declaration"]["id"]["name"]
    tree = pipeline.parse("export type X=number; function X(){}; export {X};")
    assert tree["body"][-1]["specifiers"][0]["local"]["name"] == "X"
    alias, export = pipeline.parse("export type X=number; export {X};")["body"]
    assert alias["declaration"]["id"]["name"] == export["specifiers"][0]["local"]["name"] == "X"


def test_async_private_method_after_signature_and_decorator_assertion(tmp_path):
    cls, = get_pipeline(tmp_path / "methods.ts").parse("""
    @registry!.decorate class C {
      signature()
      async #next<T>(x:T){ return await x }
      async<T>(this, x:T){ return x }
    }
    """)["body"]
    assert cls["decorators"][0]["expression"]["object"]["type"] == "TSNonNullExpression"
    signature, private, ordinary = cls["body"]["body"]
    assert signature["value"]["body"] is None
    assert private["key"]["type"] == "PrivateIdentifier" and private["value"]["async"]
    assert ordinary["key"]["name"] == "async" and not ordinary["value"]["async"]
    assert ordinary["value"]["params"][0]["name"] == "this"


def test_type_only_from_binding_and_external_alias(tmp_path):
    path = tmp_path / "component.d.html.ts"
    src = """
        import type from from './a';
        import type Asset = require('pkg');
        declare const typed: import('pkg')<T>;
        export const component: Asset;
    """
    root = get_pipeline(path).parse(src)
    default, alias, ambient, _ = root["body"]
    assert root["declarationFile"] and default["specifiers"][0]["local"]["name"] == "from"
    assert default["importKind"] == alias["importKind"] == "type"
    assert alias["moduleReference"]["expression"]["value"] == "pkg"
    ref = ambient["declarations"][0]["id"]["typeAnnotation"]["typeAnnotation"]
    assert ref["qualifier"] is None and ref["typeArguments"]["params"][0]["typeName"]["name"] == "T"


def test_ambient_prototype_and_catch_var_scope(tmp_path):
    cls, = get_pipeline(tmp_path / "types.d.ts").parse("declare class C {static prototype: C}")["body"]
    field, = cls["body"]["body"]
    assert field["static"] and field["key"]["name"] == "prototype"
    impl, = get_pipeline(tmp_path / "x.ts").parse("class C {static prototype:C}")["body"]
    assert impl["body"]["body"][0]["key"]["name"] == "prototype"
    with pytest.raises(ValueError, match="static element named prototype"):
        get_pipeline(tmp_path / "x.js").parse("class C {static prototype}")
    stmt, = get_pipeline(tmp_path / "x.ts").parse("try{}catch({x}){var x}")["body"]
    assert stmt["handler"]["param"]["type"] == "ObjectPattern"
    with pytest.raises(ValueError, match="var conflicts"):
        get_pipeline(tmp_path / "x.js").parse("try{}catch({x}){var x}")


def test_leading_amd_directives(tmp_path):
    parser = get_pipeline(tmp_path / "amd.ts")
    src = """///<amd-module name='app'/>
    /// <amd-dependency path="shared" name="dep" />
    export const x = 1;
    /// <amd-module name="ignored" />"""
    assert parser.parse(src)["references"] == [
        {"kind": "amd-module", "name": "app"},
        {"kind": "amd-dependency", "path": "shared", "name": "dep"},
    ]
    with pytest.raises(ValueError, match="line 2, column 1: duplicate AMD module name"):
        parser.parse('///<amd-module name="a"/>\n///<amd-module name="b"/>')


def test_binding_pattern_vs_parenthesized_type(tmp_path):
    tree = get_pipeline(tmp_path / "forms.ts").parse("""
    type F=({key}?: Options, [x]: Pair) => void;
    type Obj=({key:Value});
    type Result=ReturnType<<T>(v:T)
      => T>;
    let\u0085value = a << b;
    """)
    fun, obj, result, var = tree["body"]
    a, b = fun["typeAnnotation"]["params"]
    assert a["type"] == "ObjectPattern" and a["optional"] and b["type"] == "ArrayPattern"
    assert obj["typeAnnotation"]["typeAnnotation"]["type"] == "TSTypeLiteral"
    generic = result["typeAnnotation"]["typeArguments"]["params"][0]
    assert generic["type"] == "TSFunctionType" and generic["typeParameters"]["params"][0]["name"]["name"] == "T"
    assert var["declarations"][0]["init"]["operator"] == "<<"


def test_typescript_whitespace_and_arrow_linebreaks(tmp_path):
    parser = get_pipeline(tmp_path / "space.ts")
    assert parser.parse("function f(){return\u0085x}")["body"][0]["body"]["body"][0]["argument"]["name"] == "x"
    assert parser.parse("let\u200bx=1")["body"][0]["declarations"][0]["id"]["name"] == "x"
    arrow = parser.parse("(x)\n=>x")["body"][0]["expression"]
    assert arrow["type"] == "ArrowFunctionExpression" and arrow["params"][0]["name"] == "x"
    with pytest.raises(ValueError, match="line break before arrow"):
        get_pipeline(tmp_path / "space.js").parse("(x)\n=>x")


def test_less_than_rescan_only_in_type_arguments(tmp_path):
    parser = get_pipeline(tmp_path / "ambig.ts")
    good = parser.parse("const r=< <T>(x:T)=>T>f")
    assert good["body"][0]["declarations"][0]["init"]["type"] == "TSTypeAssertion"
    with pytest.raises(ValueError):
        parser.parse("const r=<<T>(x:T)=>T>f")
    alias = parser.parse("type R=ReturnType<<T>(x:T)=>T>")["body"][0]
    assert alias["typeAnnotation"]["typeArguments"]["params"][0]["type"] == "TSFunctionType"


def test_ambient_name_spaces_and_conditional_line_break(tmp_path):
    src = """
    export declare class Callable {}
    export function Callable(){}
    export type Name = string;
    export function Name(x:string):Name;
    export function Name(x:string){return x}
    export declare namespace N {export var static:any}
    interface Schema {value:number
      extends?:[]}
    """
    tree = get_pipeline(tmp_path / "names.ts").parse(src)
    prop, keyword = tree["body"][-1]["body"]["body"]
    assert prop["key"]["name"] == "value" and keyword["optional"] and keyword["key"]["name"] == "extends"
    ns = tree["body"][-2]["declaration"]
    assert ns["body"]["body"][0]["declaration"]["declarations"][0]["id"]["name"] == "static"
    dts = get_pipeline(tmp_path / "await.d.ts").parse("export {}; declare const await:any; declare class C extends await{}")
    assert dts["body"][-1]["superClass"]["name"] == "await"
    tree = get_pipeline(tmp_path / "x.ts").parse("export declare const eval:T")
    declaration = tree["body"][0]["declaration"]["declarations"][0]
    assert declaration["id"]["name"] == "eval"
    diagnostic, = declaration["diagnostics"]
    assert (diagnostic["code"], diagnostic["offset"]) == (1215, 21)


def test_optional_generic_calls(tmp_path):
    pipeline = get_pipeline(tmp_path / "call.ts")
    src = "obj?.<A<B>>(x); obj?.method<T>(x); fn<T>?.(x); obj?.method<T>;"
    first, second, third, bare = [s["expression"] for s in pipeline.parse(src)["body"]]
    first, second, third = [chain["expression"] for chain in (first, second, third)]
    assert first["optional"] and first["callee"]["name"] == "obj"
    assert first["typeArguments"]["params"][0]["typeArguments"]["params"][0]["typeName"]["name"] == "B"
    assert not second["optional"] and second["callee"]["optional"] and second["callee"]["property"]["name"] == "method"
    assert third["optional"] and third["callee"]["expression"]["name"] == "fn" and "typeArguments" not in third
    assert second["typeArguments"] == third["callee"]["typeArguments"] == bare["typeArguments"]
    assert bare["expression"]["type"] == "ChainExpression"
    assert bare["type"] == "TSInstantiationExpression"
    empty = pipeline.parse("obj?.<>()")["body"][0]["expression"]["expression"]
    assert empty["optional"] and empty["typeArguments"]["params"] == []
    for invalid in ["obj?.<T>", "obj?.<T>.field", "obj?.<>", "obj?.m<T>.p", "obj?.m<T>?.p"]:
        with pytest.raises(ValueError):
            pipeline.parse(invalid)


def test_generic_generator_modifier_names_and_rest_decorator(tmp_path):
    cls, obj = get_pipeline(tmp_path / "method.ts").parse("""
    class C {
        static public<T>(){}
        *items<T>(value:T){yield value}
        constructor(@args ...values:T[]){}
    }
    const obj={*values<T>(x:T){yield x}}
    """)["body"]
    public, items, ctor = cls["body"]["body"]
    assert public["key"]["name"] == "public" and public["static"]
    gen = obj["declarations"][0]["init"]["properties"][0]["value"]
    for fn in (items["value"], gen):
        assert fn["generator"] and not fn["async"]
        assert fn["typeParameters"]["params"][0]["name"]["name"] == "T"
    rest, = ctor["value"]["params"]
    assert rest["type"] == "RestElement" and rest["decorators"][0]["expression"]["name"] == "args"


def test_embedded_declarations_and_global_augmentation(tmp_path):
    src = """if(flag)const enum First{Item} else const enum Second{Item}
    label:function* values(){yield 1}
    declare global { class Model{}; interface Query{} }
    export {Model, Query};
    """
    branch, label, global_scope, export = get_pipeline(tmp_path / "aug.ts").parse(src)["body"]
    assert branch["consequent"]["const"] and branch["alternate"]["id"]["name"] == "Second"
    assert label["body"]["generator"] and global_scope["kind"] == "global"
    assert [s["local"]["name"] for s in export["specifiers"]] == ["Model", "Query"]
    missing = get_pipeline(tmp_path / "missing.ts").parse("declare namespace Local {interface X{}}; export {X};")
    assert missing["body"][-1]["specifiers"][0]["local"]["name"] == "X"


def test_intrinsic_alias_context_and_construct_signature(tmp_path):
    parser = get_pipeline(tmp_path / "alias.ts")
    direct, nested, qualified, shape = parser.parse("""
        type X = intrinsic;
        type Y<T extends intrinsic> = (intrinsic);
        type Z = intrinsic.Member;
        type Signatures = {new<T>(v:T): T; "new"():string; new?():void; readonly new():void};
    """)["body"]
    assert direct["typeAnnotation"] == {"type": "TSIntrinsicKeyword"}
    assert nested["typeParameters"]["params"][0]["constraint"]["typeName"]["name"] == "intrinsic"
    assert nested["typeAnnotation"]["typeAnnotation"]["type"] == "TSTypeReference"
    assert qualified["typeAnnotation"]["typeName"]["type"] == "TSQualifiedName"
    ctor, *methods = shape["typeAnnotation"]["members"]
    assert ctor["type"] == "TSConstructSignatureDeclaration" and ctor["typeParameters"]["params"][0]["name"]["name"] == "T"
    assert all(m["type"] == "TSMethodSignature" for m in methods)
    for invalid in [r"type X=\u0069ntrinsic", "type X=intrinsic[]", r"type T={ne\u0077(): T}"]:
        with pytest.raises(ValueError):
            parser.parse(invalid)


@pytest.mark.parametrize(("source", "member_path"), [
    ("const o = { get x(this: T) { return 1 }, set x(this: T, v: number) {} };",
     ("declarations", 0, "init", "properties")),
    ("class O { get x(this: T) { return 1 } set x(this: T, v: number) {} }", ("body", "body")),
    ("interface O { get x(this: T): number; set x(this: T, v: number); }", ("body", "body")),
])
def test_accessor_receiver_parameters(tmp_path, source, member_path):
    path = tmp_path / "receiver.ts"
    path.write_text(source)
    result = get_pipeline(path).analyze_file(path)
    assert result.success, result.errors
    members = result.ast["body"][0]
    for part in member_path:
        members = members[part]
    getter, setter = members
    assert [getter["kind"], setter["kind"]] == ["get", "set"]
    for method, expected in ((getter, ["this"]), (setter, ["this", "v"])):
        params = method.get("value", method)["params"]
        assert [p["name"] for p in params] == expected
        assert params[0]["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "T"


@pytest.mark.parametrize("accessor", [
    "get x(this: T, value: T): T",
    "set x(this: T)",
    "set x(this: T, ...values: T[])",
])
def test_accessor_receiver_preserves_parameters(tmp_path, accessor):
    path = tmp_path / "receiver.ts"
    path.write_text("interface T { " + accessor + "; }")
    result = get_pipeline(path).analyze_file(path)
    assert result.success, result.errors
    node = result.ast["body"][0]["body"]["body"][0]
    assert node["kind"] == accessor.split()[0] and node["params"][0]["name"] == "this"
    assert len(node["params"]) == 1 + accessor.count(",")
    if "..." in accessor:
        assert node["params"][1]["type"] == "RestElement"


def test_import_argument_types_cli(tmp_path):
    path = tmp_path / "imports.mts"
    path.write_text("""
        type Nested<T> = typeof import(import(T).Path, { with: { type: "json" } }).A.B<T>;
        type Shapes = import({ path: string } | [number]).Value;
        const load = import(target.path);
    """)
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    nested, shapes, load = ast["body"]
    query = nested["typeAnnotation"]
    assert query["type"] == "TSTypeQuery"
    imported = query["exprName"]
    assert imported["type"] == "TSImportType"
    assert imported["attributeKeyword"] == "with" and imported["attributes"][0]["value"]["value"] == "json"
    assert [imported["qualifier"][side]["name"] for side in ("left", "right")] == ["A", "B"]
    assert imported["typeArguments"]["params"][0]["typeName"]["name"] == "T"
    inner = imported["argument"]
    assert inner["type"] == "TSImportType" and inner["qualifier"]["name"] == "Path"
    assert inner["argument"]["typeName"]["name"] == "T"
    obj, tup = shapes["typeAnnotation"]["argument"]["types"]
    assert obj["members"][0]["key"]["name"] == "path"
    assert tup["elementTypes"] == [{"type": "TSNumberKeyword"}]
    assert load["declarations"][0]["init"]["source"]["type"] == "MemberExpression"


@pytest.mark.parametrize(("argument", "column"), [("", 15), ("A | ", 19), ('import("a").', 27)])
def test_incomplete_import_type_argument(tmp_path, argument, column):
    parser = get_pipeline(tmp_path / "types.ts")
    with pytest.raises(ValueError, match=rf"line 1, column {column}: unexpected '\)'"):
        parser.parse(f"type T=import({argument});")


def test_index_signature_parameters_cli(tmp_path):
    path = tmp_path / "indexers.d.ts"
    path.write_text("""
        interface I {
            readonly [key: string];
            [a?, public b: number, ...rest: string[]]: boolean;
            []: T;
            [p]: T;
            [condition ? a : b]: T;
            [a = 0]: T;
        }
        declare class Table { static [k: string,]; }
    """)
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    interface, table = ast["body"]
    readonly, many, empty, *computed = interface["body"]["body"]
    assert readonly["readonly"] and readonly["typeAnnotation"] is None
    assert readonly["parameters"][0]["typeAnnotation"]["typeAnnotation"]["type"] == "TSStringKeyword"
    a, b, rest = many["parameters"]
    assert a["name"] == "a" and a["optional"]
    assert b["name"] == "b" and b["accessibility"] == "public"
    assert b["typeAnnotation"]["typeAnnotation"]["type"] == "TSNumberKeyword"
    assert rest["type"] == "RestElement" and rest["argument"]["name"] == "rest"
    assert many["typeAnnotation"]["typeAnnotation"]["type"] == "TSBooleanKeyword"
    assert empty["type"] == "TSIndexSignature" and empty["parameters"] == []
    assert all(prop["computed"] and prop["type"] == "TSPropertySignature" for prop in computed)
    assert [prop["key"]["type"] for prop in computed] == ["Identifier", "ConditionalExpression", "AssignmentExpression"]
    index, = table["body"]["body"]
    assert index["static"] and index["typeAnnotation"] is None
    assert [p["name"] for p in index["parameters"]] == ["k"]


@pytest.mark.parametrize(("source", "column", "token", "code"), [
    ("type T = { [a:]: T };", 15, "]", 1110),
    ("class C { [a: string: number }", 21, ":", 1005),
    ("interface I { [k: string]: }", 28, "}", 1110),
])
def test_index_signature_syntax_error(tmp_path, source, column, token, code):
    with pytest.raises(ValueError) as error:
        get_pipeline(tmp_path / "indexes.ts").parse(source)
    assert (error.value.code, error.value.offset, error.value.length) == (code, column - 1, 1)
    assert f"line 1, column {column}: unexpected {token!r}" in str(error.value)


def test_type_member_modifier_order_cli(tmp_path):
    path = tmp_path / "members.d.ts"
    path.write_text("""
        interface I {
            public readonly [key: string]: number;
            protected accessor value?: string;
            abstract get
            size(): number;
            private set
            size(value: number);
            static readonly new(): I;
            public: boolean;
            readonly<T>(): T;
            public
            accessor: number;
            static
            counter: number;
        }
        type Extras = { export default class: I; const enum: string; in input: I; out result: I };
    """)
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    index, prop, getter, setter, new_method, public, readonly, line_end, accessor, counter = ast["body"][0]["body"]["body"]
    assert index["type"] == "TSIndexSignature" and index["modifiers"] == ["public", "readonly"]
    assert index["readonly"] and index["accessibility"] == "public"
    assert prop["modifiers"] == ["protected", "accessor"] and prop["optional"]
    assert [(m["kind"], m["modifiers"]) for m in (getter, setter)] == [("get", ["abstract"]), ("set", ["private"])]
    assert new_method["type"] == "TSMethodSignature" and new_method["key"]["name"] == "new"
    assert new_method["modifiers"] == ["static", "readonly"]
    assert [m["key"]["name"] for m in (public, readonly, line_end, accessor)] == ["public", "readonly", "public", "accessor"]
    assert all("modifiers" not in m for m in (public, readonly, line_end, accessor))
    assert counter["modifiers"] == ["static"]
    members = ast["body"][1]["typeAnnotation"]["members"]
    assert [m["modifiers"] for m in members] == [["export", "default"], ["const"], ["in"], ["out"]]


@pytest.mark.parametrize(("member", "column", "diagnostic"), [
    ("abstract get x():T", 12, "modifier before type accessor"),
    (r"\u0070ublic p: string", 12, "escaped type member modifier"),
    ("static static p: string", 26, "'p'"),
    ("export type: T", 19, "'type'"),
])
def test_invalid_type_member_modifier(tmp_path, member, column, diagnostic):
    with pytest.raises(ValueError) as error:
        get_pipeline(tmp_path / "members.ts").parse("type T = { " + member + " };")
    assert str(error.value) == f"line 1, column {column}: unexpected {diagnostic}"


def test_arrow_parameter_lists_cli(tmp_path):
    path = tmp_path / "params.tsx"
    path.write_text("""
        const arrow = async (public readonly x?: number = 0, ...items: T[], x: T) => x;
        const generic = <T,>(...values: T[], x: T, x: T) => { return x };
        const trailing = (...values,) => 0;
        function f(...values = [], a?: T = 1) {}
    """)
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    arrow, generic, trailing = [stmt["declarations"][0]["init"] for stmt in tree["body"][:3]]
    init, rest, duplicate = arrow["params"]
    assert arrow["async"] and arrow["expression"] and init["type"] == "AssignmentPattern"
    assert init["modifiers"] == ["public", "readonly"] and init["left"]["optional"] and init["right"]["raw"] == "0"
    assert init["left"]["typeAnnotation"]["typeAnnotation"]["type"] == "TSNumberKeyword"
    assert init["left"]["name"] == duplicate["name"] == "x"
    assert rest["type"] == "RestElement" and rest["argument"]["typeAnnotation"]["typeAnnotation"]["type"] == "TSArrayType"
    assert generic["typeParameters"]["params"][0]["name"]["name"] == "T" and not generic["expression"]
    assert [p.get("name") for p in generic["params"]] == [None, "x", "x"]
    assert trailing["params"][0]["type"] == "RestElement"
    default_rest, optional = tree["body"][3]["params"]
    assert default_rest["argument"]["right"]["type"] == "ArrayExpression"
    assert optional["left"]["optional"] and optional["right"]["raw"] == "1"


@pytest.mark.parametrize("source", ["(x,x)=>x", "(...x,)=>0", "async (...x,y)=>y", "(...x=[])=>x"])
def test_parameter_early_errors_by_language(tmp_path, source):
    assert get_pipeline(tmp_path / "params.ts").parse(source)["body"][0]["expression"]["type"] == "ArrowFunctionExpression"
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "params.js").parse(source)


@pytest.mark.parametrize("source", ["(...x,,y)=>0", "(...obj.x,y)=>0", "async(private x)", "(x?: number)"])
def test_invalid_arrow_or_call(tmp_path, source):
    with pytest.raises(ValueError, match=r"line 1, column \d+"):
        get_pipeline(tmp_path / "params.ts").parse(source)


def test_parameter_modifier_boundaries(tmp_path):
    parser = get_pipeline(tmp_path / "parameters.ts")
    tree = parser.parse("""
        class C { constructor(@inject private readonly dep: T, public ...args: T[]) {} }
        const cast = (readonly as number);
        const check = ((override) satisfies T);
        const arrow = (private satisfies: T) => 0;
    """)
    dep, rest = tree["body"][0]["body"]["body"][0]["value"]["params"]
    assert dep["decorators"][0]["expression"]["name"] == "inject"
    assert dep["modifiers"] == ["private", "readonly"]
    assert rest["modifiers"] == ["public"] and rest["type"] == "RestElement"
    cast, check, arrow = [stmt["declarations"][0]["init"] for stmt in tree["body"][1:]]
    assert cast["type"] == "TSAsExpression" and cast["expression"]["name"] == "readonly"
    assert check["type"] == "TSSatisfiesExpression" and check["expression"]["name"] == "override"
    assert arrow["params"][0]["name"] == "satisfies" and arrow["params"][0]["accessibility"] == "private"
    for source, code, index in [("(override satisfies T);", 1005, 20), ("(private as:T)=>0;", 1110, 11)]:
        with pytest.raises(ValueError) as failure:
            parser.parse(source)
        assert (failure.value.code, failure.value.offset) == (code, index)
    with pytest.raises(ValueError, match="unexpected 'rest'"):
        parser.parse("class C { constructor(...public rest: T[]) {} }")


def test_function_type_parameter_modifiers_cli(tmp_path):
    path = tmp_path / "functions.d.ts"
    path.write_text("""
        declare function f(): (public A) => Result;
        type WithPattern = (private readonly [x]: Pair, override {y}: Obj) => Value;
        type Tuple = (readonly [A]);
        type TupleParameter = (readonly [A]) => Result;
        type Named = (readonly: T) => T;
    """)
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    decl, pattern, grouped, fn, named = tree["body"]
    returned = decl["returnType"]["typeAnnotation"]
    assert returned["type"] == "TSFunctionType" and returned["returnType"]["typeName"]["name"] == "Result"
    assert returned["params"][0]["modifiers"] == ["public"] and returned["params"][0]["name"] == "A"
    array, obj = pattern["typeAnnotation"]["params"]
    assert array["type"] == "ArrayPattern" and array["modifiers"] == ["private", "readonly"]
    assert array["elements"][0]["name"] == "x" and obj["properties"][0]["value"]["name"] == "y"
    assert obj["modifiers"] == ["override"] and obj["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "Obj"
    assert grouped["typeAnnotation"]["type"] == "TSParenthesizedType"
    assert grouped["typeAnnotation"]["typeAnnotation"]["typeAnnotation"]["type"] == "TSTupleType"
    assert fn["typeAnnotation"]["params"][0]["type"] == "ArrayPattern"
    param, = named["typeAnnotation"]["params"]
    assert param["name"] == "readonly" and "modifiers" not in param


@pytest.mark.parametrize(("source", "line", "column"), [
    ("type T=(public A);", 1, 16),
    ("type T=(private\n x)=>T;", 2, 2),
    ("type T=(public A)=>;", 1, 20),
])
def test_invalid_modifier_function_type(tmp_path, source, line, column):
    with pytest.raises(ValueError, match=rf"line {line}, column {column}:"):
        get_pipeline(tmp_path / "functions.ts").parse(source)


def test_function_type_contextual_modifiers(tmp_path):
    parser = get_pipeline(tmp_path / "types.ts")
    for modifier in ("public", "private", "protected", "readonly", "override", "abstract", "accessor",
                     "async", "declare", "static", "in", "out", "export"):
        root = parser.parse(f"type F = ({modifier} arg: T) => R;")
        param, = root["body"][0]["typeAnnotation"]["params"]
        assert (param["name"], param["modifiers"]) == ("arg", [modifier])
    for source, name, modifiers in [
        ("default interface", "interface", ["default"]),
        ("static\narg", "arg", ["static"]),
        ("static static", "static", ["static"]),
        ("public in x", "x", ["public", "in"]),
    ]:
        root = parser.parse(f"type F = ({source}) => R;")
        param, = root["body"][0]["typeAnnotation"]["params"]
        assert (param["name"], param["modifiers"]) == (name, modifiers)
    for invalid in ("const arg", "default arg", "export type", "static static arg", "private this: X"):
        with pytest.raises(ValueError):
            parser.parse(f"type F = ({invalid}) => R;")


def test_marked_object_literal_cli(tmp_path):
    path = tmp_path / "object.ts"
    path.write_text("""
        const o = { x?, value?!: 1, [key]!: input, fallback? = 3,
                    async *items?!<T>(arg: T) { yield arg }, run!() { return 0 } };
        ({x?} = o);
        const arrow = (p = {x?}) => p;
    """)
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    literal, assignment, arrow = tree["body"]
    x, value, computed, fallback, items, run = literal["declarations"][0]["init"]["properties"]
    assert x["optional"] and x["shorthand"] and x["key"]["name"] == x["value"]["name"] == "x"
    assert value["optional"] and value["definite"] and value["value"]["raw"] == "1"
    assert computed["computed"] and computed["definite"] and computed["key"]["name"] == "key"
    assert fallback["shorthand"] and fallback["optional"] and fallback["value"]["right"]["raw"] == "3"
    assert items["method"] and items["optional"] and items["definite"]
    assert items["value"]["async"] and items["value"]["generator"]
    assert items["value"]["typeParameters"]["params"][0]["name"]["name"] == "T"
    assert run["method"] and run["definite"] and "optional" not in run
    assert assignment["expression"]["left"]["properties"][0]["optional"]
    assert arrow["declarations"][0]["init"]["params"][0]["right"]["properties"][0]["optional"]


@pytest.mark.parametrize(("source", "column"), [
    ("({x!? : 1})", 5), ("({x?})=>0", 4), ("async({x!:y})=>0", 14),
    ("([{outer:{x?}}])=>0", 12), ("({get x?(){}})", 8),
])
def test_invalid_object_marker(tmp_path, source, column):
    with pytest.raises(ValueError, match=rf"line 1, column {column}:"):
        get_pipeline(tmp_path / "object.ts").parse(source)


def test_private_names_cli(tmp_path):
    path = tmp_path / "private.ts"
    path.write_text(r"""
        interface Shape { readonly #x: number; #new(): T; get #v(): T; }
        class C { #constructor; #a; static #a; run(o) { return #a in o } }
        const o = { #x: 1, #m() { return this.#x } };
        delete o.#unknown;
        for (#x in o) {}
        type Private<T extends #name> = typeof #name.Inner;
    """)
    shape, cls, obj, delete, loop, alias = json.loads(subprocess.check_output(
        [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))["body"]
    prop, method, getter = shape["body"]["body"]
    assert prop["readonly"] and prop["key"] == {"type": "PrivateIdentifier", "name": "x"}
    assert method["type"] == "TSMethodSignature" and method["key"]["name"] == "new"
    assert getter["kind"] == "get" and getter["key"]["type"] == "PrivateIdentifier"
    constructor, field, static, run = cls["body"]["body"]
    assert constructor["type"] == "PropertyDefinition" and constructor["key"]["name"] == "constructor"
    assert static["static"] and static["key"] == field["key"]
    brand = run["value"]["body"]["body"][0]["argument"]
    assert brand["type"] == "BinaryExpression" and brand["operator"] == "in" and brand["left"] == field["key"]
    value, method = obj["declarations"][0]["init"]["properties"]
    assert value["key"] == prop["key"] and method["method"]
    assert delete["expression"]["argument"]["property"]["name"] == "unknown"
    assert loop["left"] == prop["key"] and loop["type"] == "ForInStatement"
    param, = alias["typeParameters"]["params"]
    assert param["constraint"] is None and param["expression"] == {"type": "PrivateIdentifier", "name": "name"}
    assert alias["typeAnnotation"]["exprName"]["left"]["name"] == "#name"


@pytest.mark.parametrize("source", [
    "o.#x", "class C { #x; #x; }", "class C { #constructor; }", "class C { #x; f() { delete this.#x } }",
])
def test_private_name_early_errors_by_language(tmp_path, source):
    assert get_pipeline(tmp_path / "private.ts").parse(source)["body"]
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "private.js").parse(source)


@pytest.mark.parametrize(("source", "column"), [
    ("o?.#x", 4), ("o?.a.#x", 6), ("o.#", 3), ("type T=A.#x", 12),
    ("({#x})", 5), ("class C extends #p.x {}", 17), ("interface I extends #p {}", 21),
])
def test_private_name_parse_errors(tmp_path, source, column):
    with pytest.raises(ValueError, match=rf"line 1, column {column}:"):
        get_pipeline(tmp_path / "private.ts").parse(source)


def test_private_identifier_type_list_lookahead(tmp_path):
    parser = get_pipeline(tmp_path / "private-types.ts")
    for source in ("A[#p]", "A<#p>", "A<X,#p>", "[X,#p]", "[#p]"):
        with pytest.raises(ValueError, match="private identifier at start of type list"):
            parser.parse("type T=" + source)
    for source in ("A[(#p)]", "A[typeof #p]", "A[X|#p]", "[...#p]", "[x:#p]", "import(#p)"):
        assert parser.parse("type T=" + source)["body"][0]["type"] == "TSTypeAliasDeclaration"


def test_async_modified_class_methods_cli(tmp_path):
    path = tmp_path / "methods.ts"
    path.write_text("""
        class C {
            async static *#values<T>(x: T) { yield await x; }
            async get #value() { return await source(); }
            async set #value(x) { await store(x); }
            async static pending(x: T): R;
            async static() {}
            async get() {}
        }
    """)
    cls, = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))["body"]
    gen, getter, setter, signature, named_static, named_get = cls["body"]["body"]
    assert gen["modifiers"] == ["async", "static"] and gen["static"] and gen["value"]["generator"]
    assert gen["value"]["async"] and gen["key"] == {"type": "PrivateIdentifier", "name": "values"}
    assert gen["value"]["typeParameters"]["params"][0]["name"]["name"] == "T"
    expr = gen["value"]["body"]["body"][0]["expression"]
    assert expr["type"] == "YieldExpression" and expr["argument"]["type"] == "AwaitExpression"
    assert getter["kind"] == "get" and setter["kind"] == "set" and getter["key"] == setter["key"]
    assert getter["value"]["async"] and getter["value"]["body"]["body"][0]["argument"]["type"] == "AwaitExpression"
    assert setter["value"]["body"]["body"][0]["expression"]["type"] == "AwaitExpression"
    assert signature["value"]["type"] == "TSDeclareFunction" and signature["value"]["body"] is None
    assert signature["value"]["returnType"]["typeAnnotation"]["typeName"]["name"] == "R"
    for method, name in ((named_static, "static"), (named_get, "get")):
        assert method["kind"] == "method" and not method["static"] and method["key"]["name"] == name


def test_jump_structure_cli(tmp_path):
    path = tmp_path / "jumps.ts"
    path.write_text("""
        outer: outer: while (ok) {
            function f() { break outer; continue missing; }
            switch (n) { default: break; case 0: continue outer; default: }
        }
        label: interface I {}
        label: const c = 1;
        break
        next;
        continue /* newline
        */ next;
    """)
    nodes = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))["body"]
    outer, interface, const, brk, next1, cont, next2 = nodes
    assert outer["label"]["name"] == outer["body"]["label"]["name"] == "outer"
    fn, switch = outer["body"]["body"]["body"]["body"]
    assert [(j["type"], j["label"]["name"]) for j in fn["body"]["body"]] == [
        ("BreakStatement", "outer"), ("ContinueStatement", "missing")]
    first, case, last = switch["cases"]
    assert first["test"] is None and first["consequent"][0]["label"] is None
    assert case["test"]["raw"] == "0" and case["consequent"][0]["label"]["name"] == "outer"
    assert last["test"] is None and last["consequent"] == []
    assert interface["body"]["type"] == "TSInterfaceDeclaration" and const["body"]["kind"] == "const"
    assert brk["label"] is None and cont["label"] is None
    assert next1["expression"]["name"] == next2["expression"]["name"] == "next"


@pytest.mark.parametrize("source", ["break missing;", "continue;", "x:x:while(1){}", "switch(x){default:;default:;}"])
def test_jump_early_errors_by_language(tmp_path, source):
    assert get_pipeline(tmp_path / "control.ts").parse(source)["body"]
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "control.js").parse(source)


@pytest.mark.parametrize("source", ["break 123;", "continue true;", "break a.b;", "label: }"])
def test_jump_invalid_syntax(tmp_path, source):
    with pytest.raises(ValueError, match="line 1, column"):
        get_pipeline(tmp_path / "control.ts").parse(source)


def test_declaration_list_cli(tmp_path):
    path = tmp_path / "lists.ts"
    path.write_text("""
        label: var;
        const a: number,;
        var {x};
        for (const of xs) {}
        for (let of of xs) {}
        for (var first = 1, b in xs) {}
        for (const; ; ) {break}
        if (ok) { using resource; }
        label: export const title: string;
        function f() { import x from "pkg"; }
    """)
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    var, const, obj, empty, named, multi, loop, cond, exported, fn = tree["body"]
    assert tree["sourceType"] == "script"
    assert var["body"] == {"type": "VariableDeclaration", "kind": "var", "declarations": []}
    assert const["trailingComma"] and const["declarations"][0]["init"] is None
    assert const["declarations"][0]["id"]["typeAnnotation"]["typeAnnotation"]["type"] == "TSNumberKeyword"
    assert obj["declarations"][0]["id"]["type"] == "ObjectPattern"
    assert empty["type"] == "ForOfStatement" and empty["left"]["declarations"] == []
    assert named["left"]["declarations"][0]["id"]["name"] == "of"
    assert multi["type"] == "ForInStatement" and [d["id"]["name"] for d in multi["left"]["declarations"]] == ["first", "b"]
    assert multi["left"]["declarations"][0]["init"]["raw"] == "1" and loop["init"]["declarations"] == []
    assert cond["consequent"]["body"][0]["kind"] == "using"
    assert exported["body"]["declaration"]["declarations"][0]["id"]["name"] == "title"
    assert fn["body"]["body"][0]["type"] == "ImportDeclaration"


@pytest.mark.parametrize("source", ["var;", "const a;", "var [a];", "for (var a,b of xs) {}", "foo: export const x = 1;"])
def test_declaration_early_errors_by_language(tmp_path, source):
    assert get_pipeline(tmp_path / "lists.ts").parse(source)["body"]
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "lists.js").parse(source)


@pytest.mark.parametrize("source", ["var ,;", "const a = ;", "for (let of xs.y) {}", "const a,,b;"])
def test_malformed_declaration_lists(tmp_path, source):
    with pytest.raises(ValueError, match="line 1, column"):
        get_pipeline(tmp_path / "lists.ts").parse(source)

def test_using_declaration_contexts(tmp_path):
    parser = get_pipeline(tmp_path / "resource.ts")
    tree = parser.parse("""
        declare await using handle: T;
        using {x} = o;
        for (using x in o);
        for (using of: T = initial;;);
        for (await using of xs);
        for (using of xs);
        using[k] = 1;
    """)
    ambient, pattern, keys, named, empty, expression, indexed = tree["body"]
    assert ambient["declare"] and ambient["kind"] == "await using" and ambient["declarations"][0]["init"] is None
    assert pattern["declarations"][0]["id"]["type"] == "ObjectPattern"
    assert keys["type"] == "ForInStatement" and keys["left"]["kind"] == "using"
    assert named["init"]["declarations"][0]["id"]["name"] == "of"
    assert empty["left"]["kind"] == "await using" and empty["left"]["declarations"] == []
    assert expression["left"] == {"type": "Identifier", "name": "using"}
    assert indexed["expression"]["left"]["type"] == "MemberExpression"


def test_let_binding_and_return_statement_boundaries(tmp_path):
    parser = get_pipeline(tmp_path / "lists.ts")
    root = parser.parse("export {}; let; const let = 0; return\nvalue;")
    _, identifier, const, ret, value = root["body"]
    assert identifier["expression"]["name"] == const["declarations"][0]["id"]["name"] == "let"
    assert ret == {"type": "ReturnStatement", "argument": None}
    assert value["expression"]["name"] == "value"
    loop, = parser.parse("for (let of let) {}")["body"]
    assert loop["left"]["declarations"] == [] and loop["right"]["name"] == "let"
    nested = parser.parse("label: var\nreturn x;")["body"]
    assert nested[0]["body"]["declarations"] == [] and nested[1]["argument"]["name"] == "x"
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "lists.js").parse("return x;")


def test_colliding_declarations_cli(tmp_path):
    path = tmp_path / "bindings.mts"
    path.write_text("""
        import {X as local, Y as local} from "m";
        export const {item, item} = source;
        export {item as x, item as x, missing};
        export default 1;
        export default 2;
        { var b; let b; }
        function f(p) { let p; for(let i;;){var i;} }
        try {} catch ({a, a}) { let a; }
        class C { constructor() {} constructor() {} }
    """)
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    imp, decl, refs, first, second, block, fn, caught, cls = root["body"]
    assert root["sourceType"] == "module"
    assert [(s["imported"]["name"], s["local"]["name"]) for s in imp["specifiers"]] == [("X", "local"), ("Y", "local")]
    assert [p["value"]["name"] for p in decl["declaration"]["declarations"][0]["id"]["properties"]] == ["item", "item"]
    assert [(s["local"]["name"], s["exported"]["name"]) for s in refs["specifiers"]] == [
        ("item", "x"), ("item", "x"), ("missing", "missing")]
    assert [n["declaration"]["raw"] for n in (first, second)] == ["1", "2"]
    assert [s["kind"] for s in block["body"]] == ["var", "let"]
    local, loop = fn["body"]["body"]
    assert fn["params"][0]["name"] == local["declarations"][0]["id"]["name"] == "p"
    assert loop["init"]["declarations"][0]["id"]["name"] == loop["body"]["body"][0]["declarations"][0]["id"]["name"] == "i"
    assert [p["value"]["name"] for p in caught["handler"]["param"]["properties"]] == ["a", "a"]
    assert [m["kind"] for m in cls["body"]["body"]] == ["constructor", "constructor"]


@pytest.mark.parametrize("source", [
    "let x; let x;", "function f(p){let p}", "for(let i;;){var i}",
    "export default 1; export default 2;", "export {missing};",
    "import {a,a} from 'm';", "class C{constructor(){} constructor(){}}",
])
def test_declaration_scope_errors_by_language(tmp_path, source):
    assert get_pipeline(tmp_path / "bindings.mts").parse(source)["body"]
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "bindings.mjs").parse(source)


@pytest.mark.parametrize("source", ["let {x:} = o;", "import {x as ,} from 'm';", "export {x as };"])
def test_malformed_declaration_names(tmp_path, source):
    with pytest.raises(ValueError, match="line 1, column"):
        get_pipeline(tmp_path / "bindings.mts").parse(source)


def test_contextual_import_bindings_cli(tmp_path):
    path = tmp_path / "bindings.mts"
    path.write_text("""
        import await from 'first';
        import * as package from 'second';
        import { public, yield as static, default as arguments, "wire-name" as interface } from 'third';
        import type { await as private } from 'types';
        function read({public: value}, [protected]) { return value }
    """)
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    default, namespace, named, typed, function = root["body"]
    assert root["sourceType"] == "module"
    assert default["specifiers"][0]["local"]["name"] == "await"
    assert namespace["specifiers"][0]["local"]["name"] == "package"
    assert [s["local"]["name"] for s in named["specifiers"]] == ["public", "static", "arguments", "interface"]
    assert named["specifiers"][-1]["imported"]["value"] == "wire-name"
    assert typed["importKind"] == "type" and typed["specifiers"][0]["imported"]["name"] == "await"
    obj, array = function["params"]
    assert obj["properties"][0]["key"]["name"] == "public" and array["elements"][0]["name"] == "protected"


def test_contextual_names_in_parameter_initializers(tmp_path):
    root = get_pipeline(tmp_path / "scope.ts").parse("""
        async function a(await, {await: alias}, {await}, x = await value) {}
        function* g(yield, {yield}, x = yield value) {}
    """)
    a, g = root["body"]
    assert a["params"][0]["name"] == a["params"][2]["properties"][0]["value"]["name"] == "await"
    assert a["params"][1]["properties"][0]["value"]["name"] == "alias"
    assert a["params"][-1]["right"] == {"type": "AwaitExpression", "argument": {"type": "Identifier", "name": "value"}}
    assert g["params"][0]["name"] == g["params"][1]["properties"][0]["value"]["name"] == "yield"
    assert g["params"][-1]["right"]["type"] == "YieldExpression" and g["params"][-1]["right"]["argument"]["name"] == "value"


@pytest.mark.parametrize("source", [
    'import { "local" } from "m"', 'import { class } from "m"', 'import { x as if } from "m"',
    'async function f(x = await) {}', 'async function f(x = {await}) {}', 'function* f(x=yield=>yield) {}',
])
def test_contextual_names_reject_malformed_syntax(tmp_path, source):
    with pytest.raises(ValueError, match="line 1, column"):
        get_pipeline(tmp_path / "bindings.mts").parse(source)


@pytest.mark.parametrize(("source", "name", "is_async", "is_generator"), [
    ("function* yield(){}", "yield", False, True),
    ("async function await<T>(){}", "await", True, False),
    ("async function* yield<T>(){}", "yield", True, True),
])
def test_contextual_function_expression_name(tmp_path, source, name, is_async, is_generator):
    parser = get_pipeline(tmp_path / "name.mts")
    expr = parser.parse("const fn = " + source)["body"][0]["declarations"][0]["init"]
    assert expr["id"]["name"] == name and expr["async"] == is_async and expr["generator"] == is_generator


def test_parenthesized_async_arrows_cli(tmp_path):
    path = tmp_path / "heads.tsx"
    path.write_text("""
        const fn = async (await, x = async (first, await, v = <C/>) => await f(v), y = await f<V>()): Promise<V> => x(y);
        const left = flag ? async(x): T => x : fallback;
        const right = flag ? async(x) : y => y;
        const newline = async (public x: T)
          => x;
    """)
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    fn, left, right, newline = [n["declarations"][0]["init"] for n in root["body"]]
    assert fn["type"] == "ArrowFunctionExpression" and fn["async"] and fn["params"][0]["name"] == "await"
    nested = fn["params"][1]["right"]
    assert nested["type"] == "ArrowFunctionExpression" and nested["async"] and nested["params"][1]["name"] == "await"
    assert nested["params"][2]["right"]["type"] == "JSXElement" and nested["body"]["type"] == "AwaitExpression"
    assert fn["params"][2]["right"]["type"] == "AwaitExpression" and fn["body"]["type"] == "CallExpression"
    assert fn["params"][2]["right"]["argument"]["typeArguments"]["params"][0]["typeName"]["name"] == "V"
    assert fn["returnType"]["typeAnnotation"]["typeName"]["name"] == "Promise"
    assert left["consequent"]["returnType"]["typeAnnotation"]["typeName"]["name"] == "T"
    assert left["alternate"]["name"] == "fallback"
    assert right["consequent"]["type"] == "CallExpression" and right["alternate"]["type"] == "ArrowFunctionExpression"
    assert newline["params"][0]["modifiers"] == ["public"]


@pytest.mark.parametrize("source", ["async\n(x)=>x", "async x\n=>x", "(async)(x)=>x", "async (x=await)=>x",
                                    "async(private ...x:T[])=>0", "async(private {x})=>0", "async(private as:T)=>0",
                                    "async function f(){return async(await)=>0}", "async(x=async(await)=>0)=>x"])
def test_async_call_is_not_an_arrow_head(tmp_path, source):
    with pytest.raises(ValueError, match="line [12], column"):
        get_pipeline(tmp_path / "heads.ts").parse(source)


def test_update_and_assignment_operands_cli(tmp_path):
    path = tmp_path / "targets.mts"
    path.write_text("""
        --1;
        obj?.[key]++;
        ++(a + b);
        get() += x = 2;
        import.meta = value;
        [...rest = fallback, last] = source;
        for (get() in obj) {}
        a
        ++b;
    """)
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    prefix, postfix, group, compound, meta, array = [s["expression"] for s in root["body"][:6]]
    assert prefix["prefix"] and prefix["operator"] == "--" and prefix["argument"]["raw"] == "1"
    assert not postfix["prefix"] and postfix["operator"] == "++"
    element = postfix["argument"]["expression"]
    assert element["optional"] and element["computed"] and element["property"]["name"] == "key"
    assert group["argument"]["type"] == "BinaryExpression" and group["argument"]["operator"] == "+"
    assert compound["left"]["type"] == "CallExpression" and compound["operator"] == "+="
    assert compound["right"]["operator"] == "=" and compound["right"]["right"]["raw"] == "2"
    assert meta["left"]["type"] == "MetaProperty" and meta["left"]["property"]["name"] == "meta"
    rest, last = array["left"]["elements"]
    assert rest["type"] == "RestElement" and rest["argument"]["type"] == "AssignmentPattern"
    assert rest["argument"]["left"]["name"] == "rest" and last["name"] == "last"
    loop, first, second = root["body"][6:]
    assert loop["type"] == "ForInStatement" and loop["left"]["type"] == "CallExpression"
    assert first["expression"]["name"] == "a" and second["expression"]["prefix"]


@pytest.mark.parametrize("source", ["--1", "obj?.x++", "++(a+b)", "import.meta = value", "for (get() of xs) {}"])
def test_target_early_errors_by_language(tmp_path, source):
    assert get_pipeline(tmp_path / "target.mts").parse(source)["body"]
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "target.mjs").parse(source)


@pytest.mark.parametrize("source", ["++-x", "++x++", "a+b=c", "a++ = c", "(obj.x)=>1", "([1])=>0", "x = ;"])
def test_malformed_target_syntax(tmp_path, source):
    with pytest.raises(ValueError, match="line 1, column"):
        get_pipeline(tmp_path / "target.ts").parse(source)


def test_optional_template_chain_cli(tmp_path):
    path = tmp_path / "tags.ts"
    path.write_text("obj?.<T>`a${n}z`.next; obj?.tag<T>`ok`; (obj?.tag)<T>`ok`;")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    chain, inherited, grouped = [s["expression"] for s in root["body"]]
    assert chain["type"] == "ChainExpression" and chain["expression"]["property"]["name"] == "next"
    tag = chain["expression"]["object"]
    assert tag["optional"] and tag["typeArguments"]["params"][0]["typeName"]["name"] == "T"
    assert [q["value"]["cooked"] for q in tag["quasi"]["quasis"]] == ["a", "z"]
    assert tag["quasi"]["expressions"][0]["name"] == "n"
    assert inherited["expression"]["optional"] is False and inherited["expression"]["tag"]["optional"]
    assert grouped["type"] == "TaggedTemplateExpression" and grouped["tag"]["type"] == "ChainExpression"
    for source in ("new obj?.x()", "a?.`b`.#p"):
        with pytest.raises(ValueError):
            get_pipeline(path).parse(source)
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "tags.js").parse("obj?.`x`")


@pytest.mark.parametrize(("source", "goal", "base", "prop"), [
    ("import.metal", "script", "import", "metal"), (r"import.m\u0065ta", "module", "import", "meta"),
    ("import.#x", "script", "import", "#x"), ("new.target", "script", "new", "target"),
    ("new.default", "script", "new", "default"), ("import.defer", "script", "import", "defer"),
])
def test_meta_property_names(tmp_path, source, goal, base, prop):
    tree = get_pipeline(tmp_path / "meta.ts").parse(source)
    assert tree["sourceType"] == goal
    meta = tree["body"][0]["expression"]
    assert meta["type"] == "MetaProperty" and meta["meta"]["name"] == base and meta["property"]["name"] == prop


def test_generic_accessor_cli(tmp_path):
    path = tmp_path / "accessors.ts"
    path.write_text("""
        interface I { get item<T>(this: I, key: T): T; set item<T>(...values: T[]) }
        class C { static get [key]<T>(first: T, second: T): T { return second; }
                  set constructor(...values: number[]) {} }
        const obj = { get item<T>(this: I, arg: T): T { return arg }, set item() {} };
        declare class D { get item<T>(): T; }
    """)
    interface, cls, const, declared = json.loads(subprocess.check_output([
        sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))["body"]
    get_sig, set_sig = interface["body"]["body"]
    assert get_sig["kind"] == "get" and get_sig["typeParameters"]["params"][0]["name"]["name"] == "T"
    assert [p["name"] for p in get_sig["params"]] == ["this", "key"]
    assert set_sig["kind"] == "set" and set_sig["params"][0]["type"] == "RestElement"
    getter, setter = cls["body"]["body"]
    assert getter["computed"] and getter["static"] and getter["key"]["name"] == "key"
    assert getter["value"]["returnType"]["typeAnnotation"]["typeName"]["name"] == "T"
    assert getter["value"]["body"]["body"][0]["argument"]["name"] == "second"
    assert setter["key"]["name"] == "constructor" and setter["kind"] == "set"
    objget, objset = const["declarations"][0]["init"]["properties"]
    assert objget["value"]["typeParameters"]["params"][0]["name"]["name"] == "T"
    assert objset["kind"] == "set" and objset["value"]["params"] == []
    assert declared["body"]["body"][0]["value"]["body"] is None


@pytest.mark.parametrize("member", ["get x(a){}", "set x(){}", "set x(a,b){}", "set x(...v){}"])
def test_accessor_arity_by_language(tmp_path, member):
    source = "class C{" + member + "}"
    assert get_pipeline(tmp_path / "a.ts").parse(source)["body"]
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "a.js").parse(source)


def test_constructor_member_kinds(tmp_path):
    tree = get_pipeline(tmp_path / "c.ts").parse("""
        class C { static constructor(){} async constructor<T>(){}
            *constructor(){} get constructor(){} "constructor"(){} "constructor"<T>(){}
            ["constructor"](){} "constructor"?: T; }
    """)
    members = tree["body"][0]["body"]["body"]
    assert [m.get("kind") for m in members] == ["constructor", "constructor", "method", "get", "constructor", "method", "method", None]
    assert members[0]["static"] and members[1]["value"]["async"] and members[2]["value"]["generator"]
    assert members[-1]["optional"] and members[-2]["computed"]
    for invalid in ("constructor?(){}", "get x?(){}", "set x(a:){}"):
        with pytest.raises(ValueError, match="line 1, column"):
            get_pipeline(tmp_path / "c.ts").parse("class C{" + invalid + "}")


def test_object_and_class_accessor_modifiers(tmp_path):
    tree = get_pipeline(tmp_path / "props.ts").parse("""
        const o = {public readonly get value<T>(x:T) {return x},
                   async set value(x){await f(x)}, public, static: 1};
        class C {export readonly get value() {return 1}
                 public static get ordered(){return 2}
                 static private get other(){return 3}}
    """)
    get, set_, public, static = tree["body"][0]["declarations"][0]["init"]["properties"]
    assert get["kind"] == "get" and get["modifiers"] == ["public", "readonly"]
    assert set_["kind"] == "set" and set_["value"]["async"] and set_["modifiers"] == ["async"]
    assert set_["value"]["body"]["body"][0]["expression"]["type"] == "AwaitExpression"
    assert public["shorthand"] and public["key"]["name"] == "public" and "modifiers" not in public
    assert static["key"]["name"] == "static" and "modifiers" not in static
    method, ordered, other = tree["body"][1]["body"]["body"]
    assert method["export"] and method["kind"] == "get" and method["modifiers"] == ["export", "readonly"]
    assert ordered["modifiers"] == ["public", "static"] and other["modifiers"] == ["static", "private"]
    with pytest.raises(ValueError, match="modifier in binding pattern"):
        get_pipeline(tmp_path / "props.ts").parse("({public x})=>x")


def test_regexp_modifier_and_diagnostic_cli(tmp_path):
    path = tmp_path / "patterns.ts"
    path.write_text(r"""
        const nested = /(?im-s:^a(?-i:(b|.)))+/u;
        const names = /(?<a>x)|(?<a>y)\k<a>/;
        const broken = /\u{110000}/u;
        const flags = /x/uu;
        const quotient = n / 2;
    """)
    body = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))["body"]
    nested, names, broken, flags, quotient = [stmt["declarations"][0]["init"] for stmt in body]
    quantified, = nested["alternatives"][0]
    outer = quantified["atom"]
    assert quantified["quantifier"] == "+" and outer["modifiers"] == {"enable": "im", "disable": "s"}
    assertion, a, inner = outer["alternatives"][0]
    assert assertion["kind"] == "^" and a["value"] == "a" and inner["modifiers"] == {"enable": "", "disable": "i"}
    capture, = inner["alternatives"][0]
    assert capture["index"] == 1 and capture["alternatives"][1] == [{"type": "Wildcard"}]
    assert [(alt[0]["name"], alt[0]["index"]) for alt in names["alternatives"]] == [("a", 1), ("a", 2)]
    assert broken["alternatives"] == [[{"type": "InvalidEscape", "value": r"\u{110000}"}]]
    assert broken["diagnostics"][0]["component"] == "pattern"
    assert broken["diagnostics"][0]["offset"] == path.read_text().index("110000")
    assert flags["alternatives"][0][0]["value"] == "x" and flags["flags"] == "uu"
    assert flags["diagnostics"] == [{"code": 1500, "length": 1, "component": "flags", "offset": path.read_text().index("uu;") + 1,
                                     "message": "duplicate RegExp flag"}]
    assert quotient["type"] == "BinaryExpression" and quotient["operator"] == "/"


@pytest.mark.parametrize("literal", ["/(abc/", "/(?ii:a)/", "/(?<n>x)(?<n>y)/", "/abc/unknown"])
def test_regex_checker_and_source_boundaries(tmp_path, literal):
    regex = get_pipeline(tmp_path / "r.ts").parse(literal)["body"][0]["expression"]
    assert regex["type"] == "RegExpLiteral" and regex["diagnostics"]
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "r.js").parse(literal)
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "r.ts").parse("/[abc/")


def test_regexp_pattern_diagnostics_and_runtime_compatibility(tmp_path):
    parser = get_pipeline(tmp_path / "regex.ts")
    legacy, valid, compatibility = [s["expression"] for s in parser.parse(
        r"/\1/; /\1(x)/; /[^\p{Emoji}\p{RGI_Emoji}]/v;"
    )["body"]]
    assert legacy["diagnostics"][0]["component"] == "pattern"
    assert legacy["alternatives"][0][0] == {"type": "Character", "value": "\x01"}
    assert valid["alternatives"][0][0] == {"type": "Backreference", "index": 1}
    assert "diagnostics" not in valid and "diagnostics" not in compatibility
    assert compatibility["compatibilityDiagnostics"] and compatibility["alternatives"][0][0]["negate"]
    with pytest.raises(ValueError, match="unterminated block comment"):
        parser.parse("/*CHECK#1/")
    comment, = parser.parse("/* comment */ /(?i:x)/;")["body"]
    assert comment["expression"]["alternatives"][0][0]["modifiers"]["enable"] == "i"


def test_regexp_dialect_is_reset_between_parses(tmp_path):
    js, ts = (get_pipeline(tmp_path / name) for name in ("patterns.js", "patterns.ts"))
    for source in ("/(?i:a)/", "/(?<name>x)|(?<name>y)/"):
        with pytest.raises(ValueError):
            js.parse(source)
        regex = ts.parse(source)["body"][0]["expression"]
        assert regex["alternatives"] and "diagnostics" not in regex
        with pytest.raises(ValueError):
            js.parse(source)
    assert js.parse("/(?:a|b)/")["body"][0]["expression"]["alternatives"]


def test_explicit_empty_generic_lists_cli(tmp_path):
    path = tmp_path / "lists.tsx"
    path.write_text("""
        class C<> extends Base<> {}
        type Alias<> = ns.Box.<Array<>,>;
        type Fn = <>() => typeof ns.Box<>;
        const empty = fn<>(), bare = fn(), typed = fn<Item,>();
        const view = <C<> a={} />;
        const fragment = <><C /></>;
        interface I extends ns.Base<>, object<> {}
    """)
    cls, alias, fn, bindings, view, fragment, interface = json.loads(subprocess.check_output([
        sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))["body"]
    empty_args = {"type": "TSTypeParameterInstantiation", "params": []}
    assert cls["typeParameters"] == alias["typeParameters"] == {"type": "TSTypeParameterDeclaration", "params": []}
    assert cls["superTypeArguments"] == empty_args
    outer = alias["typeAnnotation"]["typeArguments"]
    assert outer["dotted"] and outer["trailingComma"] and outer["params"][0]["typeArguments"] == empty_args
    assert fn["typeParameters"] is None and fn["typeAnnotation"]["typeParameters"]["params"] == []
    assert fn["typeAnnotation"]["returnType"]["typeArguments"] == empty_args
    empty, bare, typed = [d["init"] for d in bindings["declarations"]]
    assert empty["typeArguments"] == empty_args and "typeArguments" not in bare
    assert typed["typeArguments"]["trailingComma"] and typed["typeArguments"]["params"][0]["typeName"]["name"] == "Item"
    assert view["declarations"][0]["init"]["openingElement"]["typeArguments"] == empty_args
    assert fragment["declarations"][0]["init"]["type"] == "JSXFragment"
    assert [e["typeArguments"] for e in interface["extends"]] == [empty_args, empty_args]


def test_generic_list_diagnostic_spans_cli(tmp_path):
    path = tmp_path / "lists.tsx"
    source = "function f< /*𐐀*/ >(){} f<A,>(x); const view=<C<>/>; import<>(x);"
    path.write_text(source)
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    function, call, declaration, imported = root["body"]
    opening = declaration["declarations"][0]["init"]["openingElement"]
    assert function["typeParameters"]["params"] == [] and opening["typeArguments"]["params"] == []
    for node, code, spelling in ((function, 1098, "< /*𐐀*/ >"), (call["expression"], 1009, ","), (opening, 1099, "<>")):
        diagnostic, = node["diagnostics"]
        assert (diagnostic["code"], diagnostic["offset"], diagnostic["length"]) == (code, source.index(spelling), len(spelling))
    assert imported["expression"]["type"] == "ImportExpression" and imported["expression"]["diagnostics"][0]["code"] == 1323


def test_call_argument_commas_cli(tmp_path):
    path = tmp_path / "calls.ts"
    path.write_text("@d?.<T>(x,) class C extends B { constructor(){ super(x,); } } "
                    "f<T,>(x); f<T>(x,); f(x,)(y); f?.(x)(...ys,);")
    cls, plain, generic, nested, optional = json.loads(subprocess.check_output([
        sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))["body"]
    decorator = cls["decorators"][0]["expression"]["expression"]
    assert decorator["optional"] and decorator["trailingComma"]
    super_call = cls["body"]["body"][0]["value"]["body"]["body"][0]["expression"]
    assert super_call["callee"]["type"] == "Super" and super_call["trailingComma"]
    assert plain["expression"]["typeArguments"]["trailingComma"] and "trailingComma" not in plain["expression"]
    assert generic["expression"]["trailingComma"] and "trailingComma" not in generic["expression"]["typeArguments"]
    assert nested["expression"]["callee"]["trailingComma"] and "trailingComma" not in nested["expression"]
    outer = optional["expression"]["expression"]
    assert outer["trailingComma"] and outer["arguments"][0]["type"] == "SpreadElement"
    assert outer["callee"]["optional"] and "trailingComma" not in outer["callee"]


def test_dynamic_import_type_arguments(tmp_path):
    parser = get_pipeline(tmp_path / "imports.mts")
    root = parser.parse('import<>; import<T>("m", options, extra,); import.defer<>(...args); import("m",); import();')
    applied, call, deferred, trailing, noargs = [n["expression"] for n in root["body"]]
    assert applied["type"] == "TSInstantiationExpression" and applied["expression"]["type"] == "TSImportKeyword"
    assert applied["typeArguments"]["params"] == []
    assert call["type"] == "ImportExpression" and call["typeArguments"]["params"][0]["typeName"]["name"] == "T"
    assert call["source"]["value"] == "m" and call["options"]["name"] == "options"
    assert call["extraArguments"][0]["name"] == "extra" and call["trailingComma"]
    assert deferred["phase"] == "defer" and deferred["source"]["type"] == "SpreadElement"
    assert trailing["source"]["value"] == "m" and trailing["options"] is None and noargs["source"] is None

    direct, grouped = [stmt["expression"]["expression"] for stmt in
                       parser.parse('import.defer?.<T>("m",).field; (import.defer)?.("m",);')["body"]]
    assert direct["object"]["type"] == "ImportExpression" and direct["object"]["phase"] == "defer"
    assert direct["object"]["optional"] and direct["object"]["trailingComma"] and not direct["optional"]
    assert grouped["type"] == "CallExpression" and grouped["callee"]["type"] == "MetaProperty"


@pytest.mark.parametrize("source", [
    "type T=A<,>", "type T=string<>", "const f=<>(x)=>x", "const f=async <>()=>x",
    "f.<>();", "class C implements A.<> {}", "type T=A.\n<>;", "new import<T>();",
])
def test_invalid_generic_list_contexts(tmp_path, source):
    with pytest.raises(ValueError, match="line [12], column"):
        get_pipeline(tmp_path / "lists.ts").parse(source)


def test_ordered_heritage_clauses_cli(tmp_path):
    path = tmp_path / "clauses.ts"
    path.write_text("""
        class C implements One<T>, Two extends Base<> extends mixin(A), B, {}
        interface I extends extends A implements {}
        class Normal extends ns.Base<T> implements I {}
        interface Complex extends f<T>(), ns?.Base {}
        class extends {} {}
        const Named = class implements {};
        const Anonymous = class implements A {};
    """)
    cls, interface, normal, complex_, empty_base, named, anonymous = json.loads(subprocess.check_output([
        sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))["body"]
    clauses = cls["heritageClauses"]
    assert [c["kind"] for c in clauses] == ["implements", "extends", "extends"]
    assert [len(c["types"]) for c in clauses] == [2, 1, 2] and clauses[-1]["trailingComma"]
    assert clauses[0]["types"][0]["typeArguments"]["params"][0]["typeName"]["name"] == "T"
    assert clauses[1]["types"][0]["typeArguments"]["params"] == []
    call = clauses[-1]["types"][0]["expression"]
    assert call["callee"]["name"] == "mixin" and call["arguments"][0]["name"] == "A"
    assert [len(c["types"]) for c in interface["heritageClauses"]] == [0, 1, 0]
    assert normal["superClass"]["property"]["name"] == "Base" and normal["implements"][0]["typeName"]["name"] == "I"
    assert normal["superTypeArguments"]["params"][0]["typeName"]["name"] == "T"
    assert [e["expression"]["type"] for e in complex_["extends"]] == ["CallExpression", "ChainExpression"]
    assert empty_base["id"] is None and empty_base["superClass"]["type"] == "ObjectExpression"
    assert named["declarations"][0]["init"]["id"]["name"] == "implements"
    assert anonymous["declarations"][0]["init"]["implements"][0]["typeName"]["name"] == "A"


def test_declaration_prefixes_cli(tmp_path):
    path = tmp_path / "modifiers.ts"
    path.write_text("""
        public readonly interface I {}
        static
        module M {}
        async public function* f<T>(x:T) { yield await x }
        declare async function signature<T>(): T;
        declare export function exposed(): T;
        @first export @second class C {}
        export declare export = value;
        public
        var x;
    """)
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    interface, module, fn, sig, exp, cls, assignment, name, var = root["body"]
    assert root["sourceType"] == "module" and interface["modifiers"] == ["public", "readonly"]
    assert module["modifiers"] == ["static"] and module["id"]["name"] == "M"
    assert fn["modifiers"] == ["async", "public"] and fn["async"] and fn["generator"]
    assert fn["body"]["body"][0]["expression"]["argument"]["type"] == "AwaitExpression"
    assert sig["modifiers"] == ["declare", "async"] and sig["body"] is None
    assert exp["declaration"]["modifiers"] == ["declare", "export"]
    assert [(d["expression"]["name"], d["modifierIndex"]) for d in cls["declaration"]["decorators"]] == [
        ("first", 0), ("second", 1)]
    assert assignment["type"] == "TSExportAssignment" and assignment["modifiers"] == ["export", "declare"]
    assert name["expression"]["name"] == "public" and var["kind"] == "var"


@pytest.mark.parametrize("source", ["public import('m');", "static static class C{}", "@d foo()", "async public function f(){return await;}"])
def test_invalid_declaration_modifiers(tmp_path, source):
    with pytest.raises(ValueError, match="line 1, column"):
        get_pipeline(tmp_path / "mods.ts").parse(source)


def test_decorator_member_and_call_boundaries(tmp_path):
    tree = get_pipeline(tmp_path / "decor.ts").parse("""
        @new factory().wrap() export class C { @dec [key]() {} }
        @get?.[key] type T = number;
        @tag<T>`x` function f() {}
        export @label default class D {}
        @import.defer?.<T>("p",) @new.target.d @super(x,) class K { @super [key](){} }
    """)
    cls, alias, fn, default, extra = tree["body"]
    expr = cls["declaration"]["decorators"][0]["expression"]
    assert expr["type"] == "CallExpression" and expr["callee"]["property"]["name"] == "wrap"
    assert expr["callee"]["object"]["type"] == "NewExpression"
    method, = cls["declaration"]["body"]["body"]
    assert method["computed"] and method["key"]["name"] == "key" and method["decorators"][0]["expression"]["name"] == "dec"
    member = alias["decorators"][0]["expression"]["expression"]
    assert member["optional"] and member["computed"] and member["property"]["name"] == "key"
    tag = fn["decorators"][0]["expression"]
    assert tag["typeArguments"]["params"][0]["typeName"]["name"] == "T"
    assert default["type"] == "ExportDefaultDeclaration"
    assert default["declaration"]["modifiers"] == ["export", "default"]
    assert default["declaration"]["decorators"][0]["modifierIndex"] == 1

    deferred, meta, super_call = [d["expression"] for d in extra["decorators"]]
    imported = deferred["expression"]
    assert imported["type"] == "ImportExpression" and imported["phase"] == "defer"
    assert imported["optional"] and imported["trailingComma"] and imported["source"]["value"] == "p"
    assert meta["object"]["type"] == "MetaProperty" and meta["object"]["meta"]["name"] == "new"
    assert super_call["callee"]["type"] == "Super" and super_call["trailingComma"]
    decorated, = extra["body"]["body"]
    assert decorated["computed"] and decorated["key"]["name"] == "key"
    assert decorated["decorators"][0]["expression"] == {"type": "Super"}


def test_jsdoc_types_in_source_cli(tmp_path):
    path = tmp_path / "types.ts"
    path.write_text("""
        type Nullable = ?A | B;
        type Elements = !C[];
        type Pick<T> = T extends U ? function(this:T, ?, ...X=): !R : *;
        type Tuple = [name?: T?, ...rest: ...U?];
        type Path = function(module:pkg/sub.Name#member, *): Result;
        const value: *=2;
    """)
    nullable, elements, pick, tup, path_type, var = json.loads(subprocess.check_output([
        sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))["body"]
    prefix = nullable["typeAnnotation"]
    assert prefix["type"] == "JSDocNullableType" and not prefix["postfix"]
    assert prefix["typeAnnotation"]["type"] == "TSUnionType"
    assert elements["typeAnnotation"]["elementType"]["type"] == "JSDocNonNullableType"
    cond = pick["typeAnnotation"]
    assert cond["type"] == "TSConditionalType" and cond["falseType"]["type"] == "JSDocAllType"
    sig = cond["trueType"]
    assert sig["type"] == "JSDocFunctionType" and sig["returnType"]["type"] == "JSDocNonNullableType"
    receiver, unknown, variadic = sig["params"]
    assert receiver["name"]["name"] == "this" and receiver["typeAnnotation"]["typeName"]["name"] == "T"
    assert unknown["name"] is None and unknown["typeAnnotation"]["type"] == "JSDocUnknownType"
    assert variadic["typeAnnotation"]["type"] == "JSDocOptionalType"
    assert variadic["typeAnnotation"]["typeAnnotation"]["type"] == "JSDocVariadicType"
    named, rest = tup["typeAnnotation"]["elementTypes"]
    assert named["optional"] and named["elementType"]["type"] == "TSOptionalType"
    nested = rest["typeAnnotation"]["elementType"]
    assert nested["type"] == "TSRestType" and nested["typeAnnotation"]["postfix"]
    namepath = path_type["typeAnnotation"]["params"][0]["typeAnnotation"]
    assert namepath == {"type": "JSDocNamepathType", "text": "module:pkg/sub.Name#member"}
    assert var["declarations"][0]["init"]["raw"] == "2"


@pytest.mark.parametrize("source", ["type X=?;", "type X=Array<??>", "type X=function(x:T)", "type X=[A\n?]"])
def test_invalid_jsdoc_type_boundaries(tmp_path, source):
    with pytest.raises(ValueError, match="line [12], column"):
        get_pipeline(tmp_path / "types.ts").parse(source)


def test_predicate_type_contexts(tmp_path):
    tree = get_pipeline(tmp_path / "predicates.ts").parse("""
        type Test = Wrapper<this is A | B>;
        let value: asserts this
          is T;
        type Signature = function(x is A): asserts x is B;
    """)
    alias, var, jsdoc = tree["body"]
    pred, = alias["typeAnnotation"]["typeArguments"]["params"]
    assert pred["parameterName"]["type"] == "TSThisType"
    assert pred["typeAnnotation"]["typeAnnotation"]["type"] == "TSUnionType"
    assertion = var["declarations"][0]["id"]["typeAnnotation"]["typeAnnotation"]
    assert assertion["asserts"] and assertion["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "T"
    sig = jsdoc["typeAnnotation"]
    assert sig["params"][0]["typeAnnotation"]["parameterName"]["name"] == "x"
    assert sig["returnType"]["asserts"]
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "predicates.ts").parse("let value: arg is T")


def test_mapped_type_following_members(tmp_path):
    tree = get_pipeline(tmp_path / "mapped.ts").parse("""
        type M<T> = { -readonly [K in keyof T as K]+?: T[K]
            readonly field?: string; method(x: T): T; [Member in Scope]: number };
        type N = { [P in Props]; };
    """)
    mapped, plain = [d["typeAnnotation"] for d in tree["body"]]
    assert mapped["type"] == "TSMappedType" and mapped["optional"] == "+" and mapped["readonly"] == "-"
    assert mapped["typeAnnotation"]["type"] == "TSIndexedAccessType"
    field, method, computed = mapped["members"]
    assert field["optional"] and field["readonly"] and field["key"]["name"] == "field"
    assert method["params"][0]["name"] == "x" and method["returnType"]["typeAnnotation"]["typeName"]["name"] == "T"
    assert computed["computed"] and computed["key"]["operator"] == "in"
    assert not plain.get("members") and plain["typeAnnotation"] is None
    for invalid in ("[K in Keys]: T, a: U", "[K in Keys];;a:U", "[K in Keys] a:U"):
        with pytest.raises(ValueError):
            get_pipeline(tmp_path / "mapped.ts").parse("type M={" + invalid + "}")


def test_strict_with_delete_ast_and_positions(tmp_path):
    path = tmp_path / "body.ts"
    source = '''delete outside;
function f() {
    "use strict";
    with (receiver) { delete /*item*/ name; delete receiver.name; delete (name); }
}
delete after;'''
    path.write_text(source)
    outer, fn, after = json.loads(subprocess.check_output([
        sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))["body"]
    assert "diagnostics" not in outer["expression"] and "diagnostics" not in after["expression"]
    stmt = fn["body"]["body"][1]
    assert stmt["type"] == "WithStatement" and stmt["object"]["name"] == "receiver"
    assert [(d["code"], d["offset"]) for d in stmt["diagnostics"]] == [(1101, source.index("with"))]
    bare, member, grouped = [child["expression"] for child in stmt["body"]["body"]]
    assert bare["operator"] == "delete" and bare["argument"]["name"] == "name"
    assert [(d["code"], d["offset"]) for d in bare["diagnostics"]] == [(1102, source.index("name;"))]
    assert "diagnostics" not in member and "diagnostics" not in grouped
    for js in ('"use strict";with(x){}', '"use strict";delete x;'):
        with pytest.raises(ValueError):
            get_pipeline(tmp_path / "body.js").parse(js)


@pytest.mark.parametrize("source", ['"use strict";with(){}', '"use strict";delete ;'])
def test_strict_statement_syntax_errors(tmp_path, source):
    with pytest.raises(ValueError, match="line 1, column"):
        get_pipeline(tmp_path / "body.ts").parse(source)


def test_property_signature_initializers_cli(tmp_path):
    path = tmp_path / "properties.d.ts"
    path.write_text("""interface I {
        readonly p?: { q: T = make(1 + 2 * 3) } = source;
        get = value;
        [key()] = obj.member
    }
    type A = { name
        = 42, plain: number };
    """)
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    iface, alias = root["body"]
    prop, get, computed = iface["body"]["body"]
    assert prop["type"] == "TSPropertySignature" and prop["optional"] and prop["readonly"]
    assert prop["initializer"]["name"] == "source"
    inner, = prop["typeAnnotation"]["typeAnnotation"]["members"]
    call = inner["initializer"]
    assert call["type"] == "CallExpression" and call["callee"]["name"] == "make"
    add, = call["arguments"]
    assert add["operator"] == "+" and add["right"]["operator"] == "*"
    assert get["key"]["name"] == "get" and get["initializer"]["name"] == "value"
    assert computed["computed"] and computed["key"]["type"] == "CallExpression"
    assert computed["initializer"]["property"]["name"] == "member"
    initialized, plain = alias["typeAnnotation"]["members"]
    assert initialized["initializer"]["raw"] == "42" and "initializer" not in plain


@pytest.mark.parametrize("member", ["p=1", "'p'=1", "readonly p=1", "p:T=", "f():T=1"])
def test_invalid_property_initializers(tmp_path, member):
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "property.ts").parse("interface I {" + member + "}")


@pytest.mark.parametrize("declaration", ["interface I", "type I ="])
def test_type_accessor_implementation_cli(tmp_path, declaration):
    path = tmp_path / "accessors.ts"
    path.write_text(declaration + """ {
        readonly get
        [key]<T>(): {x:T} { return {x: first()}; }
        set value(v:T) { this.field = v; } next:T;
        get last():T;
    }""")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    owner, = tree["body"]
    members = owner["body"]["body"] if declaration.startswith("interface") else owner["typeAnnotation"]["members"]
    getter, setter, prop, signature = members
    assert getter["type"] == "TSMethodSignature" and getter["readonly"] and getter["computed"]
    assert getter["key"]["name"] == "key" and getter["typeParameters"]["params"][0]["name"]["name"] == "T"
    assert getter["returnType"]["typeAnnotation"]["members"][0]["key"]["name"] == "x"
    ret, = getter["body"]["body"]
    assert ret["type"] == "ReturnStatement" and ret["argument"]["properties"][0]["value"]["callee"]["name"] == "first"
    assignment = setter["body"]["body"][0]["expression"]
    assert assignment["left"]["property"]["name"] == "field" and assignment["right"]["name"] == "v"
    assert prop["key"]["name"] == "next" and "body" not in signature


def test_object_signature_without_body_cli(tmp_path):
    path = tmp_path / "object.ts"
    path.write_text("""const o={
        async *stream<T>(value:T):T;,
        get [key]():T;,
        set size(v:number);,
        concrete(){return 1}, last?()
    }""")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    stream, getter, setter, concrete, last = tree["body"][0]["declarations"][0]["init"]["properties"]
    fn = stream["value"]
    assert stream["method"] and fn["type"] == "TSDeclareFunction" and fn["body"] is None
    assert fn["async"] and fn["generator"] and fn["params"][0]["name"] == "value"
    assert fn["typeParameters"]["params"][0]["name"]["name"] == fn["returnType"]["typeAnnotation"]["typeName"]["name"]
    assert getter["kind"] == "get" and getter["computed"] and getter["value"]["body"] is None
    assert setter["kind"] == "set" and setter["value"]["params"][0]["typeAnnotation"]["typeAnnotation"]["type"] == "TSNumberKeyword"
    assert concrete["value"]["body"]["body"][0]["type"] == "ReturnStatement"
    assert last["optional"] and last["value"]["body"] is None
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "object.js").parse("const o={last()}")


def test_export_modified_imports_cli(tmp_path):
    path = tmp_path / "imports.ts"
    path.write_text("""export import main, {type A, b as c} from "pkg";
        export import "side";
        export import type * as types from "declarations";
        export import defer * as lazy from "deferred";
        export import alias = require("legacy");""")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    assert tree["sourceType"] == "module"
    assert all(stmt["type"] == "ExportNamedDeclaration" for stmt in tree["body"])
    mixed, side, typed, deferred, alias = [stmt["declaration"] for stmt in tree["body"]]
    assert mixed["type"] == "ImportDeclaration" and mixed["source"]["value"] == "pkg"
    default, named_type, renamed = mixed["specifiers"]
    assert default["local"]["name"] == "main" and named_type["importKind"] == "type"
    assert renamed["imported"]["name"] == "b" and renamed["local"]["name"] == "c"
    assert not side["specifiers"] and side["source"]["value"] == "side"
    assert typed["importKind"] == "type" and typed["specifiers"][0]["type"] == "ImportNamespaceSpecifier"
    assert deferred["phase"] == "defer" and deferred["specifiers"][0]["local"]["name"] == "lazy"
    assert alias["type"] == "TSImportEqualsDeclaration" and alias["id"]["name"] == "alias"


def test_module_clause_and_source_expressions_cli(tmp_path):
    path = tmp_path / "phases.ts"
    path.write_text("""import defer from from "pkg";
        import defer {type as as} from "pkg";
        import {type as as other} from "pkg";
        import mod = require(resolve(a,b));
        export * from ("root" + suffix);
        export type {K} from namespaceName;
        import defer from "ordinary";""")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    default, deferred, typed, alias, star, named, ordinary = tree["body"]
    assert default["phase"] == "defer" and default["specifiers"][0]["local"]["name"] == "from"
    spec, = deferred["specifiers"]
    assert deferred["phase"] == "defer" and spec["imported"]["name"] == "type" and spec["local"]["name"] == "as"
    assert "importKind" not in spec and typed["specifiers"][0]["importKind"] == "type"
    call = alias["moduleReference"]["expression"]
    assert call["type"] == "CallExpression" and [a["name"] for a in call["arguments"]] == ["a", "b"]
    assert star["source"]["operator"] == "+" and star["source"]["left"]["value"] == "root"
    assert named["exportKind"] == "type" and named["source"]["name"] == "namespaceName"
    assert "phase" not in ordinary and ordinary["specifiers"][0]["local"]["name"] == "defer"


def test_generator_overload_cli(tmp_path):
    path = tmp_path / "generators.ts"
    path.write_text("""function* f<T>(value:T):Iterator<T>;
        function* f(value){yield value}
        declare class C {static async *[key]?<T>(v:T): AsyncIterator<T>; *constructor(): Iterator<number>;}
        export default function*<T>(v:T):Iterator<T>;""")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    decl, impl, cls, wrapper = tree["body"]
    assert decl["type"] == "TSDeclareFunction" and decl["generator"] and decl["body"] is None
    assert decl["id"]["name"] == impl["id"]["name"] == "f"
    assert decl["params"][0]["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "T"
    assert impl["body"]["body"][0]["expression"]["type"] == "YieldExpression"
    method, ctor = cls["body"]["body"]
    assert method["static"] and method["computed"] and method["optional"] and method["key"]["name"] == "key"
    assert method["value"]["async"] and method["value"]["generator"] and method["value"]["body"] is None
    assert ctor["kind"] == "method" and ctor["value"]["generator"]
    anonymous = wrapper["declaration"]
    assert anonymous["id"] is None and anonymous["typeParameters"]["params"][0]["name"]["name"] == "T"
    assert anonymous["returnType"]["typeAnnotation"]["typeName"]["name"] == "Iterator"
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "gen.js").parse("function* f();")


def test_class_field_definite_marker_cli(tmp_path):
    path = tmp_path / "fields.ts"
    path.write_text("class C {a!; static #b!:T=make(); [key]! = 1 + 2; other!:T; opt?:T;}")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    a, b, computed, typed, optional = tree["body"][0]["body"]["body"]
    assert all(p["type"] == "PropertyDefinition" and p["definite"] and not p["optional"] for p in [a, b, computed, typed])
    assert a["value"] is None and a["typeAnnotation"] is None
    assert b["static"] and b["key"]["type"] == "PrivateIdentifier" and b["value"]["callee"]["name"] == "make"
    assert computed["computed"] and computed["key"]["name"] == "key" and computed["value"]["operator"] == "+"
    assert typed["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "T" and typed["value"] is None
    assert optional["optional"] and not optional.get("definite")


@pytest.mark.parametrize("member", ["x\n!:T", "x?!:T", "constructor!:T", "x!(){}"])
def test_class_field_marker_syntax_errors(tmp_path, member):
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "fields.ts").parse("class C{" + member + "}")


def test_variable_definite_markers(tmp_path):
    pipeline = get_pipeline(tmp_path / "variables.ts")
    simple, initialized, typed, both = pipeline.parse("let a!, b! = 1, c!:T, d!:T = build(c);")["body"][0]["declarations"]
    assert all(d["definite"] for d in (simple, initialized, typed, both))
    assert simple["init"] is None and initialized["init"]["raw"] == "1"
    assert typed["id"]["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "T"
    assert both["init"]["callee"]["name"] == "build" and both["init"]["arguments"][0]["name"] == "c"
    for src in ["for(let x! in xs){}", "for(let x!:T=0;;){}", "const [x]! = xs;"]:
        with pytest.raises(ValueError):
            pipeline.parse(src)


@pytest.mark.parametrize(("filename", "prefix"), [("ambient.d.ts", ""), ("ambient.ts", "declare ")])
def test_ambient_generator_expression_children(tmp_path, filename, prefix):
    fn, = get_pipeline(tmp_path / filename).parse(prefix + "function* f(){yield* items; yield;}")["body"]
    delegated, bare = [stmt["expression"] for stmt in fn["body"]["body"]]
    assert delegated["type"] == "YieldExpression" and delegated["delegate"] and delegated["argument"]["name"] == "items"
    assert bare["type"] == "YieldExpression" and bare["argument"] is None and not bare["delegate"]


def test_class_const_modifier_cli(tmp_path):
    path = tmp_path / "fields.ts"
    path.write_text("""class C {
        const static p = 4;
        const #q:T;
        const *g(){yield this.p;}
        const static { init(); }
        const = 1;
        const
        enum;
    }""")
    program = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    field, private, method, block, named, separated, following = program["body"][0]["body"]["body"]
    assert field["modifiers"] == ["const", "static"] and field["value"]["raw"] == "4"
    assert private["key"]["type"] == "PrivateIdentifier" and private["modifiers"] == ["const"]
    assert method["value"]["generator"] and method["modifiers"] == ["const"]
    assert block["type"] == "StaticBlock" and block["modifiers"] == ["const"]
    assert block["body"][0]["expression"]["callee"]["name"] == "init"
    assert named["key"]["name"] == "const" and named["value"]["raw"] == "1"
    assert separated["key"]["name"] == "const" and following["key"]["name"] == "enum"
    assert all("modifiers" not in n for n in (named, separated, following))


def test_async_class_member_modifiers_cli(tmp_path):
    path = tmp_path / "members.ts"
    path.write_text("""class C {
        async static { register(); }
        async override m<T>(v:T) {return await v;}
        async readonly static *stream() {yield await next();}
        async abstract load():T;
        async override [key]!:T = make();
        static async #name?:string;
    }""")
    program = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    block, method, stream, load, field, private = program["body"][0]["body"]["body"]
    assert block["type"] == "StaticBlock" and block["modifiers"] == ["async"]
    assert block["body"][0]["expression"]["callee"]["name"] == "register"
    assert method["modifiers"] == ["async", "override"]
    ret = method["value"]["body"]["body"][0]
    assert ret["argument"]["type"] == "AwaitExpression" and ret["argument"]["argument"]["name"] == "v"
    assert stream["modifiers"] == ["async", "readonly", "static"]
    expr = stream["value"]["body"]["body"][0]["expression"]
    assert expr["type"] == "YieldExpression" and expr["argument"]["type"] == "AwaitExpression"
    assert load["value"]["type"] == "TSDeclareFunction" and load["value"]["body"] is None
    assert field["definite"] and field["computed"] and field["value"]["callee"]["name"] == "make"
    assert private["modifiers"] == ["static", "async"] and private["optional"] and private["key"]["type"] == "PrivateIdentifier"


def test_rest_binding_contexts_cli(tmp_path):
    path = tmp_path / "rest.ts"
    pattern = "{...[key()]:[first,, ...tail=seed,]=values, ...others, after,}"
    path.write_text(f"const {pattern}=src; function f({pattern}){{}} const g=(arg,{pattern})=>after;")
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    decl, function, arrow_decl = ast["body"]
    binding = decl["declarations"][0]["id"]
    assert binding == function["params"][0] == arrow_decl["declarations"][0]["init"]["params"][1]
    named, others, after = binding["properties"]
    assert binding["trailingComma"] and named["computed"] and named["type"] == "RestElement"
    assert named["propertyName"]["callee"]["name"] == "key"
    assignment = named["argument"]
    assert assignment["type"] == "AssignmentPattern" and assignment["right"]["name"] == "values"
    array = assignment["left"]
    first, hole, rest = array["elements"]
    assert array["trailingComma"] and first["name"] == "first" and hole is None
    assert rest["argument"]["left"]["name"] == "tail" and rest["argument"]["right"]["name"] == "seed"
    assert others["argument"]["name"] == "others" and after["value"]["name"] == "after"
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "rest.js").parse(f"const {pattern}=src;")


def test_rest_arrow_probe_context(tmp_path):
    parse = get_pipeline(tmp_path / "arrow.ts").parse
    first, second = parse("const f=({...k:v}, x=await)=>x; const g=({...k:v}, x=await expr)=>x;")["body"]
    assert first["declarations"][0]["init"]["params"][1]["right"]["type"] == "Identifier"
    assert second["declarations"][0]["init"]["params"][1]["right"]["type"] == "AwaitExpression"
    assert parse("fn({...obj}, v);")["body"][0]["expression"]["arguments"][0]["type"] == "ObjectExpression"
    for invalid in ["fn({...x:y})", "({...x:y})", "const f=({...[x]})=>x"]:
        with pytest.raises(ValueError):
            parse(invalid)


def test_iteration_expression_targets_cli(tmp_path):
    path = tmp_path / "loops.ts"
    path.write_text("""for (v++ of values) {}
        for (a = 1 in b, c) {}
        for await (async of source) {}
        for (a, flag ? key in obj : other of (x,y)) {}""")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    update, assign, awaited, sequence = tree["body"]
    assert update["type"] == "ForOfStatement" and update["left"]["type"] == "UpdateExpression"
    assert not update["left"]["prefix"] and update["left"]["argument"]["name"] == "v"
    assert assign["type"] == "ForInStatement" and assign["left"]["right"]["raw"] == "1"
    assert [n["name"] for n in assign["right"]["expressions"]] == ["b", "c"]
    assert awaited["await"] and awaited["left"]["name"] == "async"
    first, conditional = sequence["left"]["expressions"]
    assert first["name"] == "a" and conditional["consequent"]["operator"] == "in"
    assert sequence["right"]["type"] == "SequenceExpression"
    for source in ["for (v++ of xs) {}", "for (a=1 in b) {}", "for (async of xs) {}"]:
        with pytest.raises(ValueError):
            get_pipeline(tmp_path / "loops.js").parse(source)
    for source in ["for (let.x of xs) {}", "for await (x in xs) {}", "for (x of a,b) {}"]:
        with pytest.raises(ValueError):
            get_pipeline(path).parse(source)


def test_mixed_nullish_and_computed_comma_cli(tmp_path):
    path = tmp_path / "operators.ts"
    path.write_text("const o={ [first(), second]: a ?? b || c && d }; class C{ [x(),y](){return a || b ?? c;} }")
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    decl, cls = ast["body"]
    prop = decl["declarations"][0]["init"]["properties"][0]
    assert prop["computed"] and prop["key"]["type"] == "SequenceExpression"
    call, second = prop["key"]["expressions"]
    assert call["callee"]["name"] == "first" and second["name"] == "second"
    logical = prop["value"]
    assert logical["operator"] == "||" and logical["left"]["operator"] == "??" and logical["right"]["operator"] == "&&"
    method = cls["body"]["body"][0]
    first, second = method["key"]["expressions"]
    assert first["callee"]["name"] == "x" and second["name"] == "y"
    value = method["value"]["body"]["body"][0]["argument"]
    assert value["operator"] == "??" and value["left"]["operator"] == "||"
    for source in ["a ?? b || c", "({[a,b]: x})"]:
        with pytest.raises(ValueError):
            get_pipeline(tmp_path / "operators.js").parse(source)


def test_modifier_order_on_type_parameters_cli(tmp_path):
    path = tmp_path / "parameters.ts"
    path.write_text("type A<public readonly T, out in out U extends Base=Child, const V> = T; class C{in a=0; out b=1}")
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    alias, cls = ast["body"]
    first, second, third = alias["typeParameters"]["params"]
    assert first["modifiers"] == ["public", "readonly"] and first["name"]["name"] == "T"
    assert second["modifiers"] == ["out", "in", "out"] and second["in"] and second["out"]
    assert second["constraint"]["typeName"]["name"] == "Base" and second["default"]["typeName"]["name"] == "Child"
    assert third["const"] and third["modifiers"] == ["const"]
    assert [field["modifiers"] for field in cls["body"]["body"]] == [["in"], ["out"]]


def test_throw_line_break_and_super_constructor_cli(tmp_path):
    path = tmp_path / "throw.ts"
    src = '"𐐀"; throw /*\n*/ new super<T>(arg,).field; new C<T>; new C<T>(); new C()?.[#x];'
    path.write_text(src)
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    _, thrown, stmt, bare, empty, chain = ast["body"]
    assert thrown["type"] == "ThrowStatement" and thrown["argument"] is None
    assert thrown["missingArgumentOffset"] == src.index("throw") + 5
    expr = stmt["expression"]
    assert expr["type"] == "MemberExpression" and expr["property"]["name"] == "field"
    ctor = expr["object"]
    assert ctor["type"] == "NewExpression" and ctor["callee"] == {"type": "Super"}
    assert ctor["typeArguments"]["params"][0]["typeName"]["name"] == "T" and ctor["arguments"][0]["name"] == "arg"
    assert ctor["hasArgumentList"] and ctor["trailingComma"]
    assert not bare["expression"]["hasArgumentList"] and empty["expression"]["hasArgumentList"]
    assert bare["expression"]["arguments"] == empty["expression"]["arguments"] == []
    access = chain["expression"]["expression"]
    assert access["type"] == "MemberExpression" and access["optional"] and access["computed"]
    assert access["object"]["type"] == "NewExpression" and access["property"] == {"type": "PrivateIdentifier", "name": "x"}
    for source, expected in ((r"a<T>?.#\u0078;", (18030, 6, 7)), ("new C<T /*gap*/ >.p;", (1477, 5, 12))):
        with pytest.raises(SourceSyntaxError) as failure:
            get_pipeline(path).parse(source)
        assert (failure.value.code, failure.value.offset, failure.value.length) == expected
    for source, expected in (("super /*gap*/ <T>(x,);", (2754, 5, 12)), ("super?.(x);", (1034, 5, 2)),
                             ("super /*gap*/", (1034, 13, 0)), ("await; super?.[import.meta];", (1109, 5, 1))):
        with pytest.raises(SourceSyntaxError) as failure:
            get_pipeline(path).parse(source)
        assert (failure.value.code, failure.value.offset, failure.value.length) == expected
    for source in ["throw\nx", "new super()"]:
        with pytest.raises(ValueError):
            get_pipeline(tmp_path / "test.js").parse(source)


def test_leading_union_intersection_nodes(tmp_path):
    nodes = get_pipeline(tmp_path / "types.ts").parse(
        "type U=|string; type I=&number; type Both=| &A & B | C; type Plain=T;")["body"]
    union, intersection, both, plain = [n["typeAnnotation"] for n in nodes]
    assert union == {"type": "TSUnionType", "types": [{"type": "TSStringKeyword"}]}
    assert intersection == {"type": "TSIntersectionType", "types": [{"type": "TSNumberKeyword"}]}
    members, last = both["types"]
    assert members["type"] == "TSIntersectionType" and [n["typeName"]["name"] for n in members["types"]] == ["A", "B"]
    assert last["typeName"]["name"] == "C" and plain["type"] == "TSTypeReference"


@pytest.mark.parametrize(("parameter", "field", "kind"), [
    ("T", None, None),
    ("T extends -1", "constraint", "TSLiteralType"),
    ("T extends +count = R", "expression", "UnaryExpression"),
    ("T extends make", "constraint", "TSTypeReference"),
    ("T extends /abc/.test(key)", "expression", "CallExpression"),
])
def test_type_parameter_constraint_branch(tmp_path, parameter, field, kind):
    alias, = get_pipeline(tmp_path / "constraint.ts").parse(f"type A<{parameter}> = T;")["body"]
    p, = alias["typeParameters"]["params"]
    assert p["name"]["name"] == "T"
    if field:
        assert p[field]["type"] == kind
    assert ("expression" in p) == (field == "expression")
    assert (p["constraint"] is not None) == (field == "constraint")
    if "= R" in parameter:
        assert p["default"]["typeName"]["name"] == "R" and p["expression"]["argument"]["name"] == "count"
    else:
        assert p["default"] is None


def test_nested_try_switch_cli(tmp_path):
    path = tmp_path / "switch.ts"
    path.write_text("""try {
        switch (choose()) {
            case one:
            case two: try { act(); } finally { inner(); } break;
            default: fallback();
        }
    } catch ({cause:e}: unknown) { handle(e); } finally { outer(); }""")
    program = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    stmt, = program["body"]
    switch, = stmt["block"]["body"]
    one, two, default = switch["cases"]
    assert switch["discriminant"]["callee"]["name"] == "choose"
    assert one["test"]["name"] == "one" and one["consequent"] == []
    inner, jump = two["consequent"]
    assert two["test"]["name"] == "two" and jump["type"] == "BreakStatement"
    assert inner["handler"] is None and inner["finalizer"]["body"][0]["expression"]["callee"]["name"] == "inner"
    assert default["test"] is None and default["consequent"][0]["expression"]["callee"]["name"] == "fallback"
    binding = stmt["handler"]["param"]
    assert binding["properties"][0]["value"]["name"] == "e"
    assert binding["typeAnnotation"]["typeAnnotation"]["type"] == "TSUnknownKeyword"
    assert stmt["finalizer"]["body"][0]["expression"]["callee"]["name"] == "outer"


def test_export_dispatch_and_declaration_lookahead_cli(tmp_path):
    path = tmp_path / "exports.ts"
    path.write_text("""declare type A = T;
        type();
        export default factory();
        export = api.current;
        export as namespace API;
        export type {A as PublicA};""")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    alias, call, default, assignment, namespace, named = root["body"]
    assert root["sourceType"] == "module"
    assert alias["declare"] and alias["id"]["name"] == "A"
    assert call["expression"]["callee"]["name"] == "type"
    assert default["type"] == "ExportDefaultDeclaration" and default["declaration"]["callee"]["name"] == "factory"
    assert assignment["type"] == "TSExportAssignment" and assignment["expression"]["property"]["name"] == "current"
    assert namespace["type"] == "TSNamespaceExportDeclaration" and namespace["id"]["name"] == "API"
    spec, = named["specifiers"]
    assert named["exportKind"] == "type" and spec["local"]["name"] == "A" and spec["exported"]["name"] == "PublicA"


def test_side_effect_import_expression_cli(tmp_path):
    path = tmp_path / "sources.ts"
    path.write_text("""import true, next;
        import defer (factory());
        import defer [a,b] with {"mode": setting};
        import this.key;
        import (42);""")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    sequence, call, array, member, dynamic = root["body"]
    assert root["sourceType"] == "module"
    assert all(stmt["type"] == "ImportDeclaration" and stmt["specifiers"] == [] for stmt in root["body"][:4])
    left, right = sequence["source"]["expressions"]
    assert left["value"] is True and right["name"] == "next"
    assert call["source"]["callee"]["name"] == "factory" and "phase" not in call
    assert [n["name"] for n in array["source"]["elements"]] == ["a", "b"]
    attr, = array["attributes"]
    assert attr["key"]["value"] == "mode" and attr["value"]["name"] == "setting"
    assert member["source"]["object"]["type"] == "ThisExpression"
    assert dynamic["expression"]["type"] == "ImportExpression"
    for source in ["import 42;", "import [item];", "import defer d;"]:
        with pytest.raises(ValueError):
            get_pipeline(path).parse(source)


def test_non_null_chain_boundaries_cli(tmp_path):
    path = tmp_path / "chains.ts"
    path.write_text("a?.b!!.c; a?.b!`t`.#p; a?.b<T>?.(); a?.b!?.<U>(v); @a?.b!`t`.c class C{}")
    program = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    continued, tagged, instantiated, explicit = [s["expression"] for s in program["body"][:4]]
    outer = continued["expression"]["object"]
    assert outer["optional"] is False and outer["expression"]["optional"] is False
    assert tagged["property"]["type"] == "PrivateIdentifier" and "optional" not in tagged
    tag = tagged["object"]
    assert tag["type"] == "TaggedTemplateExpression" and "optional" not in tag
    assert tag["tag"]["expression"]["type"] == "ChainExpression"
    call = instantiated["expression"]
    assert call["optional"] and "typeArguments" not in call and call["callee"]["type"] == "TSInstantiationExpression"
    typed_call = explicit["expression"]
    assert typed_call["typeArguments"]["params"][0]["typeName"]["name"] == "U" and typed_call["arguments"][0]["name"] == "v"
    deco = program["body"][4]["decorators"][0]["expression"]
    assert deco["property"]["name"] == "c" and "optional" not in deco and "optional" not in deco["object"]
    with pytest.raises(ValueError, match="property access after unparenthesized instantiation"):
        get_pipeline(path).parse("a<T>.#p")


def test_jsx_spread_attribute_expression_cli(tmp_path):
    path = tmp_path / "view.tsx"
    path.write_text("const v=<UI.View<T> {...first,second} child=<b/>><>{...items}</></UI.View>;")
    program = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    jsx = program["body"][0]["declarations"][0]["init"]
    opening = jsx["openingElement"]
    assert opening["name"]["object"]["name"] == "UI" and opening["name"]["property"]["name"] == "View"
    assert opening["typeArguments"]["params"][0]["typeName"]["name"] == "T"
    spread, child = opening["attributes"]
    assert spread["type"] == "JSXSpreadAttribute" and spread["argument"]["type"] == "SequenceExpression"
    assert [expr["name"] for expr in spread["argument"]["expressions"]] == ["first", "second"]
    assert child["value"]["openingElement"]["selfClosing"]
    inner, = jsx["children"][0]["children"]
    assert inner["type"] == "JSXSpreadChild" and inner["expression"]["name"] == "items"
    assert jsx["closingElement"]["name"] == opening["name"]


def test_jsx_expression_continuation_cli(tmp_path):
    path = tmp_path / "continuations.tsx"
    path.write_text("<A/>\n[x]; (<B/>).key; typeof <C/> < limit; <D/> ** 2;")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    first, array, member, comparison, power = [stmt["expression"] for stmt in tree["body"]]
    assert first["type"] == "JSXElement" and array["elements"][0]["name"] == "x"
    assert member["object"]["type"] == "JSXElement" and member["property"]["name"] == "key"
    assert comparison["operator"] == "<" and comparison["left"]["operator"] == "typeof"
    assert power["operator"] == "**" and power["left"]["type"] == "JSXElement"
    for source in ["<A/>.key", "<A/>()", "<A/> < limit", "<A/><B/>", "x + <A/> < limit"]:
        with pytest.raises(ValueError):
            get_pipeline(path).parse(source)

    adjacent = "<A<T>/> /* gap */ <><B/></>\r\n<C>𐐀</C>"
    source = "const node = " + adjacent + ";"
    path.write_text(source)
    rejected = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                              capture_output=True, text=True)
    assert rejected.returncode and "TS2657" in rejected.stderr and json.loads(rejected.stdout) is None
    with pytest.raises(SourceSyntaxError) as failure:
        get_pipeline(path).parse(source)
    assert (failure.value.code, failure.value.offset, failure.value.length) == (2657, source.index("<"), len(adjacent))

    for source, diagnostic in (("await; <A/><B/> => v; export {};", "TS1109"),
                               ("new /*gap*/ <A/>;", "TS1109"), ("<A/>\r\n=> v;", "TS1128")):
        path.write_text(source)
        rejected = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                                  capture_output=True, text=True)
        assert rejected.returncode and diagnostic in rejected.stderr and json.loads(rejected.stdout) is None


def test_template_source_spelling_cli(tmp_path):
    path = tmp_path / "spelling.ts"
    path.write_bytes(b"const value = tag`head\r\n${x}\\x41${y}\\\r\ntail`; type T = `\\8`;")
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    decl, alias = ast["body"]
    template = decl["declarations"][0]["init"]["quasi"]
    head, middle, tail = template["quasis"]
    assert head["rawText"] == "head\r\n" and head["value"] == {"raw": "head\n", "cooked": "head\n"}
    assert middle["value"] == {"raw": r"\x41", "cooked": "A"} and not middle["tail"]
    assert tail["rawText"] == "\\\r\ntail" and tail["value"]["cooked"] == "tail" and tail["tail"]
    assert [e["name"] for e in template["expressions"]] == ["x", "y"]
    assert alias["typeAnnotation"]["quasis"][0]["value"] == {"raw": r"\8", "cooked": None}
    for source in [r"`\8`", r"type T = `\8${X}`"]:
        with pytest.raises(ValueError):
            get_pipeline(path).parse(source)


def test_contextual_arrow_defaults_cli(tmp_path):
    path = tmp_path / "parameters.ts"
    path.write_text("""export {};
        const f=(x=await work, y=yield value)=>x;
        const single=async await=>0;
        async function outer(){const g=(x=await)=>x;}""")
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    _, decl, single, outer = ast["body"]
    first, second = decl["declarations"][0]["init"]["params"]
    assert first["right"]["type"] == "AwaitExpression" and first["right"]["argument"]["name"] == "work"
    assert second["right"]["type"] == "YieldExpression" and second["right"]["argument"]["name"] == "value"
    arrow = single["declarations"][0]["init"]
    assert arrow["async"] and arrow["params"][0]["name"] == "await"
    default = outer["body"]["body"][0]["declarations"][0]["init"]["params"][0]["right"]
    assert default == {"type": "Identifier", "name": "await"}
    for source in ["async function f(){async await=>0}", "class C{static{(await)=>0}}"]:
        with pytest.raises(ValueError):
            get_pipeline(path).parse(source)


def test_arrow_context_in_nested_class_field(tmp_path):
    parser = get_pipeline(tmp_path / "field.ts")
    outer, = parser.parse("class Outer{static{class Inner{x=await; f=(x=await)=>x;}}}")["body"]
    inner, = outer["body"]["body"][0]["body"]
    field, arrow = inner["body"]["body"]
    assert field["value"] == {"type": "Identifier", "name": "await"}
    default = arrow["value"]["params"][0]["right"]
    assert default == field["value"]
    with pytest.raises(ValueError):
        parser.parse("class Outer{static{(await)=>x;}}")


def test_parameter_decorator_await_context_cli(tmp_path):
    path = tmp_path / "decorated.ts"
    path.write_text("""async function inn(@dec(await) value=await load()){}
        async function outer(){function inner(@dec(await load()) value=await){}}""")
    program = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    direct, outer = program["body"]
    first = direct["params"][0]
    second = outer["body"]["body"][0]["params"][0]
    assert first["decorators"][0]["expression"]["arguments"][0] == {"type": "Identifier", "name": "await"}
    assert first["right"]["type"] == "AwaitExpression" and first["right"]["argument"]["callee"]["name"] == "load"
    arg = second["decorators"][0]["expression"]["arguments"][0]
    assert arg["type"] == "AwaitExpression" and arg["argument"]["callee"]["name"] == "load"
    assert second["right"] == {"type": "Identifier", "name": "await"}


@pytest.mark.parametrize(("source", "marked"), [
    ("function f(public readonly this:T){}", "public"),
    ("class C{m(@first @next this:T){}}", "@first"),
    ("function f(...this:T){}", "this"),
    ("async function f(){class C{m(@await x){}}}", "await"),
    ("namespace N{export class C{async m(@await p){}}}", "await"),
])
def test_parameter_diagnostic_offset(tmp_path, source, marked):
    with pytest.raises(ValueError) as error:
        get_pipeline(tmp_path / "parameters.ts").parse(source)
    assert error.value.offset == source.index(marked)


def test_keyword_named_tuple_elements_cli(tmp_path):
    path = tmp_path / "tuple.ts"
    path.write_text("type R=[readonly:T, true?:U, ...default:V[], ...#private?:W[]];")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    first, optional, rest, private = tree["body"][0]["typeAnnotation"]["elementTypes"]
    assert first["label"]["name"] == "readonly" and first["elementType"]["typeName"]["name"] == "T"
    assert optional["optional"] and optional["label"]["name"] == "true"
    assert rest["type"] == "TSRestType" and rest["typeAnnotation"]["label"]["name"] == "default"
    assert private["typeAnnotation"]["optional"] and private["typeAnnotation"]["label"]["name"] == "#private"
    for source in ['type R=[class: U]', 'type R=["name": U]', 'type R=[#private: U]']:
        with pytest.raises(ValueError):
            get_pipeline(path).parse(source)


def test_class_semicolons_and_heritage_cli(tmp_path):
    path = tmp_path / "members.ts"
    path.write_text('class C extends Base<T> implements I {;field:T;; static {} ; "constructor"(v:T){};}')
    program = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    cls, = program["body"]
    assert cls["superClass"]["name"] == "Base" and cls["superTypeArguments"]["params"][0]["typeName"]["name"] == "T"
    assert cls["implements"][0]["typeName"]["name"] == "I"
    members = cls["body"]["body"]
    assert [m["type"] for m in members] == [
        "SemicolonClassElement", "PropertyDefinition", "SemicolonClassElement", "StaticBlock",
        "SemicolonClassElement", "MethodDefinition", "SemicolonClassElement",
    ]
    assert members[5]["kind"] == "constructor" and members[5]["value"]["params"][0]["name"] == "v"


def test_dotted_namespace_enum_cli(tmp_path):
    path = tmp_path / "names.ts"
    path.write_text("""module A.default.C { export const enum E { One=1, [getKey()]=One+2, } }
        namespace A.#inner {}
        async function f(){enum Names {Value=await, Other=await work}}
        function* g(){enum Names {Value=yield}}
    """)
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    a, ns, f, g = ast["body"]
    b, c = a["body"], a["body"]["body"]
    assert [(n["kind"], n["id"]["name"]) for n in [a,b,c]] == [("module", "A"), ("module", "default"), ("module", "C")]
    enum = c["body"]["body"][0]["declaration"]
    assert enum["const"] and enum["trailingComma"] and enum["members"][0]["initializer"]["raw"] == "1"
    member = enum["members"][1]
    assert member["computed"] and member["id"]["callee"]["name"] == "getKey" and member["initializer"]["operator"] == "+"
    assert ns["body"]["kind"] == "namespace" and ns["body"]["id"]["name"] == "#inner"
    a, b = f["body"]["body"][0]["members"]
    assert a["initializer"]["name"] == "await" and b["initializer"]["type"] == "AwaitExpression"
    assert g["body"]["body"][0]["members"][0]["initializer"]["name"] == "yield"


def test_standalone_declare_boundary(tmp_path):
    parse = get_pipeline(tmp_path / "declarations.ts").parse
    left, right = parse("declare global;")["body"]
    assert [n["expression"]["name"] for n in (left, right)] == ["declare", "global"]
    assert parse("declare as T;")["body"][0]["expression"]["type"] == "TSAsExpression"
    assert parse("global\n{}")["body"][0]["kind"] == "global"
    augmentation, call = parse("declare global\nordinary();")["body"]
    assert augmentation["kind"] == "global" and augmentation["declare"] and augmentation["body"] is None
    assert call["expression"]["callee"]["name"] == "ordinary"
    assert parse("global as T;")["body"][0]["expression"]["type"] == "TSAsExpression"
    with pytest.raises(ValueError, match="line 2, column 1"):
        parse("declare type\nX=T;")
    with pytest.raises(ValueError):
        parse("const x=declare foo;")


def test_accessor_keyword_and_private_key_cli(tmp_path):
    path = tmp_path / "keys.ts"
    cli = [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]
    path.write_text("({get #set(){return x}, #get(){}, get<T>(x:T){return x}});")
    root = json.loads(subprocess.check_output(cli, text=True))
    accessor, private_method, generic = root["body"][0]["expression"]["properties"]
    assert accessor["kind"] == "get" and accessor["key"] == {"type": "PrivateIdentifier", "name": "set"}
    assert private_method["method"] and private_method["key"] == {"type": "PrivateIdentifier", "name": "get"}
    assert generic["kind"] == "init" and generic["value"]["typeParameters"]["params"][0]["name"]["name"] == "T"
    for source, code, column in [("({0xFFg:v});", 1005, 7), ("({#get x(){}});", 1005, 8),
                                 ("function f<#const T>(){}", 1139, 12), ("type F<const #in>=T;", 18016, 14)]:
        path.write_text(source)
        result = subprocess.run(cli, text=True, capture_output=True)
        assert result.returncode and f"TS{code}" in result.stderr and f"column {column}:" in result.stderr


def test_committed_arrow_parameter_cli(tmp_path):
    path = tmp_path / "head.ts"
    cli = [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]
    for source, code, offset in [("const f=(...#x)=>x;", 18009, 12), ("async(...x);", 1005, 11),
                                 ("await; async(...x); export {};", 1109, 5), ("const f=(#x)=>x;", 1005, 12),
                                 ("const f=(#x:T)=>x;", 1005, 11), ("([#x])=>x;", 18016, 2),
                                 ("const f=(x+y)=>x;", 1005, 13), ("const f=(...a.b)=>v;", 1005, 13),
                                 ("await; const f=(...a())=>v; export {};", 1109, 5),
                                 ("await; const f=(...a(𐐀)().b)=>v; export {};", 1109, 5),
                                 ("await; const f=(...a()[import.meta])=>v;", 1109, 5),
                                 ("await; const f=(...a[import.meta])=>v;", 1005, 20),
                                 ("await; const f=(...a[x+y])=>v; export {};", 1109, 5),
                                 ("function f([import.meta]){}", 1181, 12),
                                 ("await; const f=(...a(import.meta))=>v;", 1109, 5),
                                 ('await; const f=(...a(import("p")))=>v;', 1005, 20)]:
        path.write_text(source)
        result = subprocess.run(cli, text=True, capture_output=True)
        assert result.returncode and f"TS{code}" in result.stderr and f"column {offset + 1}:" in result.stderr
    path.write_text("const f=async (...xs:T[])=>xs; f(...#x, ...a!().items?.[key]); flag?(x+y):z=>z;")
    declaration, stmt, choice = json.loads(subprocess.check_output(cli, text=True))["body"]
    conditional = choice["expression"]
    assert conditional["type"] == "ConditionalExpression" and conditional["consequent"]["operator"] == "+"
    assert conditional["alternate"]["type"] == "ArrowFunctionExpression"
    arrow = declaration["declarations"][0]["init"]
    rest, = arrow["params"]
    assert arrow["async"] and rest["type"] == "RestElement"
    assert rest["argument"]["name"] == "xs" and arrow["body"]["name"] == "xs"
    spread, chained = stmt["expression"]["arguments"]
    assert spread == {"type": "SpreadElement", "argument": {"type": "PrivateIdentifier", "name": "x"}}
    assert chained["type"] == "SpreadElement" and chained["argument"]["type"] == "ChainExpression"
    index = chained["argument"]["expression"]
    assert index["computed"] and index["optional"] and index["property"]["name"] == "key"
    member = index["object"]
    assert member["type"] == "MemberExpression" and member["property"]["name"] == "items"
    call = member["object"]
    assert call["type"] == "CallExpression" and call["arguments"] == []
    assert call["callee"] == {"type": "TSNonNullExpression", "expression": {"type": "Identifier", "name": "a"}}


def test_private_parameter_and_binding_cli(tmp_path):
    path = tmp_path / "binding.ts"
    cli = [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]
    path.write_text("function f({#x:y}){return y}")
    tree = json.loads(subprocess.check_output(cli, text=True))
    prop, = tree["body"][0]["params"][0]["properties"]
    assert prop["key"] == {"type": "PrivateIdentifier", "name": "x"}
    assert prop["value"]["name"] == "y" and not prop["shorthand"]
    for source, code, offset in [("function f(#x){}", 18009, 11), ("function f({x:#y}){}", 18016, 14),
                                 ("try{}catch(#x){}", 18029, 11), ("await; function f(#x:T){} export {};", 1109, 5)]:
        path.write_text(source)
        result = subprocess.run(cli, text=True, capture_output=True)
        assert result.returncode and f"TS{code}" in result.stderr and f"column {offset + 1}:" in result.stderr


def test_numeric_literal_tokens_and_ast_cli(tmp_path):
    path = tmp_path / "numbers.ts"
    literals = [".5", "1.", "1.e2", "0B1_0n", "0o6_7", "0XF_F", "12_3.4_5E-6_7", "1e+2"]
    source = "/*𐐀*/\r\n[" + ",".join(literals[:-1]) + ",-" + literals[-1] + "];"
    path.write_bytes(source.encode("utf-8"))
    cli = [sys.executable, "-m", "orionparser"]
    tokens = json.loads(subprocess.check_output([*cli, "tokens", str(path), "--json"]))
    numbers = [(t["value"], t["offset"], t["line"]) for t in tokens if t["type"] == "NUMBER"]
    assert numbers == [(raw, source.index(raw), 2) for raw in literals]
    root = json.loads(subprocess.check_output([*cli, "parse", str(path), "--json"]))
    elements = root["body"][0]["expression"]["elements"]
    assert elements[-1]["type"] == "UnaryExpression" and elements[-1]["operator"] == "-"
    assert [*elements[:-1], elements[-1]["argument"]] == [
        {"type": "BigIntLiteral" if raw.endswith("n") else "NumericLiteral", "raw": raw}
        for raw in literals
    ]

    path.write_text("0b1in obj; 0o7satisfies T;")
    body = json.loads(subprocess.check_output([*cli, "parse", str(path), "--json"]))["body"]
    binary, assertion = (stmt["expression"] for stmt in body)
    assert binary["operator"] == "in" and binary["left"]["raw"] == "0b1" and binary["right"]["name"] == "obj"
    assert assertion["type"] == "TSSatisfiesExpression" and assertion["expression"]["raw"] == "0o7"
    for text, code, column in [(".1foo;", 1351, 3), ("1e+;", 1124, 4), ("1.0n;", 1353, 1),
                               ("1__2;", 6189, 3), ("0x_1;", 6188, 3), ("0xFFg;", 1005, 5),
                               ("0x1.;", 1003, 5)]:
        path.write_text(text)
        rejected = subprocess.run([*cli, "parse", str(path), "--json"], capture_output=True, text=True)
        assert rejected.returncode and f"TS{code}" in rejected.stderr and f"column {column}:" in rejected.stderr


@pytest.mark.parametrize("escape", [r"\1", r"\08", r"\00", r"\177", r"\8", r"\9"])
def test_legacy_string_escapes_in_ts_script(tmp_path, escape):
    path = tmp_path / "escapes.ts"
    pipeline = get_pipeline(path)
    source = 'const value = "' + escape + '";'
    with pytest.raises(ValueError, match="legacy decimal escape") as rejected:
        pipeline.parse(source)
    assert rejected.value.offset == source.index("\\")
    accepted = pipeline.parse(r'["\0", "\\8", "\x38", "\u{38}"];')
    elements = accepted["body"][0]["expression"]["elements"]
    assert [element["value"] for element in elements] == ["\0", r"\8", "8", "8"]


def test_html_comment_delimiters_are_operators_cli(tmp_path):
    path = tmp_path / "operators.ts"
    path.write_text("a<!--b; // next expression\r\nc/*\u2028*/+d;", encoding="utf-8")
    args = [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]
    first, second = json.loads(subprocess.check_output(args))["body"]
    comparison = first["expression"]
    assert comparison["operator"] == "<" and comparison["left"]["name"] == "a"
    negation = comparison["right"]
    assert negation["operator"] == "!" and negation["argument"] == {
        "type": "UpdateExpression", "prefix": True, "operator": "--",
        "argument": {"type": "Identifier", "name": "b"},
    }
    assert second["expression"] == {
        "type": "BinaryExpression", "operator": "+", "left": {"type": "Identifier", "name": "c"},
        "right": {"type": "Identifier", "name": "d"},
    }
    for source, offset in [("<!-- hi\nx;", 2), ("--> hi\nx;", 2), ("a\n-->b;", 4)]:
        with pytest.raises(ValueError) as rejected:
            get_pipeline(path).parse(source)
        assert rejected.value.offset == offset


def test_reference_attribute_scanning_cli(tmp_path):
    path = tmp_path / "references.ts"
    path.write_text('\u200b/// <reference path="first" PATH="second" />\n'
                    '/// <reference types="pkg" resolution-mode="" />\n'
                    '/// <amd-dependency path="lib" name="a" name="b" />\n'
                    'const x = 1;', encoding="utf-8")
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    assert ast["references"] == [{"kind": "path", "value": "first"}, {"kind": "types", "value": "pkg"},
                                 {"kind": "amd-dependency", "path": "lib", "name": "a"}]
    source = '/*𐐀*/\r\n/// <reference types="pkg" resolution-mode="bad" />'
    with pytest.raises(ValueError) as rejected:
        get_pipeline(path).parse(source)
    assert rejected.value.offset == source.index("pkg")


def test_jsdoc_parameter_line_leading_asterisk_cli(tmp_path):
    path = tmp_path / "signature.ts"
    path.write_text("type A = function(T\n* | U, [X,\n* Y], function\n* (Z)): Q;", encoding="utf-8")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    signature = tree["body"][0]["typeAnnotation"]
    union, pair, nested = [param["typeAnnotation"] for param in signature["params"]]
    assert union["type"] == "TSUnionType" and [t["typeName"]["name"] for t in union["types"]] == ["T", "U"]
    assert pair["type"] == "TSTupleType" and [t["typeName"]["name"] for t in pair["elementTypes"]] == ["X", "Y"]
    assert nested["type"] == "JSDocFunctionType" and nested["params"][0]["typeAnnotation"]["typeName"]["name"] == "Z"
    assert signature["returnType"]["typeName"]["name"] == "Q"
    for text in ["function(T\n*\n* | U)", "function(\n* T)", "function(...T=\n* )", "function():T\n* | U"]:
        with pytest.raises(ValueError):
            get_pipeline(path).parse(f"type A={text};")


def test_jsx_attribute_trivia_cli(tmp_path):
    path = tmp_path / "attributes.tsx"
    source = r'''<A direct="\x41" spaced= "\x41" quoted=/*gap*/'a\'b' / /*close*/ >;'''
    path.write_text(source, encoding="utf-8")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    opening = root["body"][0]["expression"]["openingElement"]
    assert opening["selfClosing"]
    assert [(a["value"]["raw"], a["value"]["value"]) for a in opening["attributes"]] == [
        (r'"\x41"', r"\x41"), (r'"\x41"', "A"), (r"'a\'b'", "a'b")]
    parser = get_pipeline(path)
    multiline = parser.parse('<A x="a\nb"/\r\n>;')["body"][0]["expression"]
    assert multiline["openingElement"]["attributes"][0]["value"]["value"] == "a\nb"
    for invalid in ['<A x= "a\nb"/>', r'<A x= "\8"/>', '<A/ /* unclosed >']:
        with pytest.raises(ValueError):
            parser.parse(invalid)


@pytest.mark.parametrize(("source", "code", "shift", "length"), [
    ("const s = `𐐀\r\nwrong\\8`;", 1488, 0, 2),
    ("const s = `ok\r\n${x}bad\\01${y}also\\9`;", 1487, 0, 3),
    ("type T = `𐐀${X}ok${Y}\r\nbad\\xZ`;", 1125, 2, 0),
    ("const s = `head${tag`nested`}tail\\u{}`;", 1125, 3, 0),
])
def test_template_escape_offset(tmp_path, source, code, shift, length):
    path = tmp_path / "escape.ts"
    path.write_bytes(source.encode("utf-8"))
    with pytest.raises(ValueError) as failure:
        get_pipeline(path).parse(source)
    assert (failure.value.code, failure.value.offset, failure.value.length) == (code, source.index("\\") + shift, length)
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            capture_output=True, text=True)
    assert result.returncode and str(failure.value) in result.stderr


def test_merge_conflict_markers_cli(tmp_path):
    path = tmp_path / "merge.tsx"
    parser = get_pipeline(path)
    for marker in ("<<<<<<< HEAD", "||||||| base", "=======", ">>>>>>> other"):
        source = "const text = '𐐀';\r\n" + marker + "\nnext;"
        with pytest.raises(ValueError, match="TS1185") as failure:
            parser.parse(source)
        assert failure.value.offset == source.index(marker)
    path.write_text("<A>text\u2028<<<<<<< HEAD\nnext</A>;", encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            capture_output=True, text=True)
    assert result.returncode and "line 2, column 1:" in result.stderr and "TS1185" in result.stderr
    ast = parser.parse("<A>\n=======\n</A>;")
    assert ast["body"][0]["expression"]["children"][0]["value"] == "\n=======\n"


def test_repeated_proto_properties_cli(tmp_path):
    path = tmp_path / "object.ts"
    path.write_text('const value = {__proto__: left, ...middle, "__proto__": right};')
    result = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    props = result["body"][0]["declarations"][0]["init"]["properties"]
    first, spread, last = props
    assert first["key"] == {"type": "Identifier", "name": "__proto__"} and first["value"]["name"] == "left"
    assert spread == {"type": "SpreadElement", "argument": {"type": "Identifier", "name": "middle"}}
    assert last["key"]["type"] == "Literal" and last["key"]["value"] == "__proto__" and last["value"]["name"] == "right"


def test_async_object_member_prefixes_cli(tmp_path):
    path = tmp_path / "members.ts"
    path.write_text("({async async x, public async y=1, async static *[k](){yield await run()}, async! : v});")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    repeated, defaulted, method, named = root["body"][0]["expression"]["properties"]
    assert repeated["shorthand"] and repeated["modifiers"] == ["async", "async"]
    assert defaulted["modifiers"] == ["public", "async"] and defaulted["value"]["right"]["raw"] == "1"
    assert method["computed"] and method["key"]["name"] == "k" and method["modifiers"] == ["async", "static"]
    fn = method["value"]
    assert fn["generator"] and fn["async"]
    expr = fn["body"]["body"][0]["expression"]
    assert expr["type"] == "YieldExpression" and expr["argument"]["type"] == "AwaitExpression"
    assert named["definite"] and named["key"]["name"] == "async" and "modifiers" not in named


def test_decorators_between_object_modifiers(tmp_path):
    parser = get_pipeline(tmp_path / "decorated.ts")
    source = "({public async export @first @second(v) readonly f(){return await v}});"
    member, = parser.parse(source)["body"][0]["expression"]["properties"]
    assert member["modifiers"] == ["public", "async", "export", "readonly"]
    first, second = member["decorators"]
    assert first == {"type": "Decorator", "expression": {"type": "Identifier", "name": "first"}, "modifierIndex": 3}
    assert second["modifierIndex"] == 3 and second["expression"]["callee"]["name"] == "second"
    assert member["value"]["body"]["body"][0]["argument"]["type"] == "AwaitExpression"
    for invalid in ["({export @d ...rest});", "({async export @a public default @b x});"]:
        with pytest.raises(ValueError):
            parser.parse(invalid)


def test_access_trivia_diagnostic_positions(tmp_path):
    parser = get_pipeline(tmp_path / "access.ts")
    for source, code, offset in [('o.\r\nkey in rhs;', 1003, 2), ('o?.\nkey satisfies T;', 1003, 3),
                                 ('o[ /*gap*/ ];', 1011, 2), ('o?.[\n ];', 1011, 4)]:
        with pytest.raises(ValueError, match=f"TS{code}") as rejected:
            parser.parse(source)
        assert rejected.value.offset == offset
    access = parser.parse("o.\nkey\nin rhs;")["body"][0]["expression"]
    assert access["operator"] == "in" and access["left"]["property"]["name"] == "key"
    assert parser.parse('type T=import("m").\nX extends Y ? A:B;')["body"][0]["typeAnnotation"]["type"] == "TSConditionalType"


def test_namespaced_jsx_tag_cli(tmp_path):
    path = tmp_path / "tags.tsx"
    cli = [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]
    path.write_text("<ns:A ns:x='1'><UI.Icon/></ns:A>")
    root = json.loads(subprocess.check_output(cli, text=True))["body"][0]["expression"]
    opening = root["openingElement"]
    assert opening["name"] == root["closingElement"]["name"]
    assert opening["name"]["type"] == "JSXNamespacedName" and opening["name"]["name"]["name"] == "A"
    assert opening["attributes"][0]["name"]["namespace"]["name"] == "ns"
    member = root["children"][0]["openingElement"]["name"]
    assert member["type"] == "JSXMemberExpression" and member["property"]["name"] == "Icon"
    for source, code in [("<ns:A.B/>", 1003), ("<Root></ns:A.B>", 1005)]:
        path.write_text(source)
        result = subprocess.run(cli, text=True, capture_output=True)
        assert result.returncode and f"TS{code}" in result.stderr and f"column {source.index('.') + 1}:" in result.stderr


def test_dotted_jsx_name_hyphen(tmp_path):
    parser = get_pipeline(tmp_path / "tags.tsx")
    for source, code, length in [("<A.B-c/>", 1003, 1), ("<A.B.C-x/>", 1003, 1),
                                 ("<A></A.B--c>", 1005, 2), ("<A.B-=x/>", 1003, 2)]:
        with pytest.raises(ValueError) as rejected:
            parser.parse(source)
        assert (rejected.value.code, rejected.value.offset, rejected.value.length) == (code, source.index("-"), length)
    member = parser.parse("<a-b.C data-x/>")["body"][0]["expression"]["openingElement"]["name"]
    assert member["object"]["name"] == "a-b" and member["property"]["name"] == "C"


def test_ambient_async_function_body_cli(tmp_path):
    path = tmp_path / "declarations.d.ts"
    path.write_text("export declare const await:T; declare async function* f<T>(x:T):T{yield await x}")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    binding, function = root["body"]
    assert binding["declaration"]["declarations"][0]["id"]["name"] == "await"
    assert function["async"] and function["generator"]
    yielded = function["body"]["body"][0]["expression"]
    assert yielded["type"] == "YieldExpression"
    assert yielded["argument"] == {"type": "AwaitExpression", "argument": {"type": "Identifier", "name": "x"}}


def test_arrow_line_terminator_grammar_diagnostic_cli(tmp_path):
    path = tmp_path / "arrows.mts"
    source = "const f=<T>(x=1) /*𐐀\r\n*/ =>{'use strict';}; const g=x=>y\n=>y;"
    path.write_text(source)
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    first, outer = [stmt["declarations"][0]["init"] for stmt in root["body"]]
    assert [(d["code"], d["offset"]) for d in first["diagnostics"]] == [(7060, source.index("T")), (1200, source.index("=>"))]
    assert first["diagnostics"][1]["length"] == 2
    assert "diagnostics" not in first["params"][0] and "diagnostics" not in first["body"]["body"][0]
    assert "diagnostics" not in outer
    assert outer["body"]["diagnostics"][0]["offset"] == source.rindex("=>")


def test_exported_class_heritage_await_cli(tmp_path):
    source = "export declare class C<T> extends Base<T>, await {x:1};"
    path = tmp_path / "heritage.ts"
    path.write_text(source)
    cli = [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]
    decl, following = json.loads(subprocess.check_output(cli))["body"]
    cls = decl["declaration"]
    clause, = cls["heritageClauses"]
    assert clause["kind"] == "extends" and clause["trailingComma"]
    assert clause["types"][0]["typeName"]["name"] == "Base"
    assert cls["body"] == {"type": "ClassBody", "body": [], "missing": True}
    assert following["expression"]["type"] == "AwaitExpression"
    prop, = following["expression"]["argument"]["properties"]
    assert prop["key"]["name"] == "x" and prop["value"]["raw"] == "1"
    for suffix in [".d.ts", ".d.mts", ".d.cts"]:
        with pytest.raises(ValueError, match="TS1109") as error:
            get_pipeline(tmp_path / ("heritage" + suffix)).parse(source)
        assert error.value.offset == source.index("await")
    cls = get_pipeline(path).parse("export class C extends (await getBase()) {}")["body"][0]["declaration"]
    assert cls["superClass"]["type"] == "AwaitExpression" and cls["superClass"]["argument"]["type"] == "CallExpression"


def test_exported_computed_await_cli(tmp_path):
    path = tmp_path / "member.d.ts"
    path.write_text("export declare class C{static [await load()]():T; [o.await]:T; value=[await]}")
    cli = [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]
    members = json.loads(subprocess.check_output(cli))["body"][0]["declaration"]["body"]["body"]
    assert members[0]["computed"] and members[0]["static"] and members[0]["key"]["type"] == "AwaitExpression"
    assert members[0]["key"]["argument"]["callee"]["name"] == "load"
    assert members[1]["key"]["property"]["name"] == "await"
    assert members[2]["value"]["elements"] == [{"type": "Identifier", "name": "await"}]
    for member in ["[await]():T", "[f(await)]?:T", "static [await.x]:T", "[{await}]:T"]:
        with pytest.raises(ValueError):
            get_pipeline(path).parse("export declare class C{" + member + "}")


def test_module_class_signature_keeps_script_await(tmp_path):
    pipeline = get_pipeline(tmp_path / "signature.mts")
    source = "class C { [await]():T; field=o.await }"
    cls = pipeline.parse(source)["body"][0]
    assert cls["body"]["body"][0]["key"] == {"type": "Identifier", "name": "await"}
    for source in ("class C{[await]():T; field=await}", "class C{[await](){}}",
                   "export class C { [await]():T; field=o.await }"):
        with pytest.raises(ValueError):
            pipeline.parse(source)
    cls = pipeline.parse("class C{[await + x](){}}")["body"][0]
    key = cls["body"]["body"][0]["key"]
    assert key["type"] == "AwaitExpression" and key["argument"]["operator"] == "+"


def test_await_shorthand_in_module_function_scopes(tmp_path):
    pipeline = get_pipeline(tmp_path / "scopes.d.mts")
    members = pipeline.parse("export declare class C{field={await=1}; *g(){yield {await}}}")["body"][0]["declaration"]["body"]["body"]
    defaulted, = members[0]["value"]["properties"]
    assert defaulted["shorthand"] and defaulted["value"]["left"]["name"] == "await"
    yielded = members[1]["value"]["body"]["body"][0]["expression"]
    shorthand, = yielded["argument"]["properties"]
    assert yielded["type"] == "YieldExpression" and shorthand["shorthand"] and shorthand["key"]["name"] == "await"
    for member in ["async m(){return {await}}", "[async()=>({await})]:T"]:
        with pytest.raises(ValueError):
            pipeline.parse("export declare class C{" + member + "}")


def test_type_declaration_context_cli(tmp_path):
    path = tmp_path / "names.ts"
    cli = [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]
    path.write_text("export type await<T>=T; declare interface yield {p:await<number>}"
                    " export default @a @b const n=1;")
    tree = json.loads(subprocess.check_output(cli, text=True))
    exported, interface, default = tree["body"]
    variable = default["declaration"]
    binding, = variable["declarations"]
    assert default["type"] == "ExportDefaultDeclaration" and variable["kind"] == "const"
    assert binding["id"]["name"] == "n" and binding["init"] == {"type": "NumericLiteral", "raw": "1"}
    assert variable["modifiers"] == ["export", "default"]
    assert [(d["expression"]["name"], d["modifierIndex"]) for d in variable["decorators"]] == [("a", 2), ("b", 2)]
    alias = exported["declaration"]
    assert tree["sourceType"] == "module" and exported["type"] == "ExportNamedDeclaration"
    assert alias["id"]["name"] == "await" and alias["typeAnnotation"]["typeName"]["name"] == "T"
    member, = interface["body"]["body"]
    assert interface["declare"] and interface["id"]["name"] == "yield"
    assert member["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "await"
    for src, key, code in [("async function f(){type await=T;}", "await", 2457),
                           ("function* f(){interface yield{}}", "yield", 2427),
                           ("async function f(){declare type await=T;}", "await", 1003)]:
        path.write_text(src)
        result = subprocess.run(cli, text=True, capture_output=True)
        assert result.returncode and f"TS{code}" in result.stderr and f"column {src.index(key) + 1}:" in result.stderr


def test_module_shorthand_replay_cli(tmp_path):
    path = tmp_path / "keywords.ts"
    path.write_text("({await, yield}); export {};")
    cli = [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]
    tree = json.loads(subprocess.check_output(cli, text=True))
    props = tree["body"][0]["expression"]["properties"]
    assert tree["sourceType"] == "module"
    assert [(p["shorthand"], p["key"]["name"], p["value"]["name"]) for p in props] == [
        (True, "await", "await"), (True, "yield", "yield")]
    path.write_text("export {}; await ({await});")
    failure = subprocess.run(cli, text=True, capture_output=True)
    assert failure.returncode and "TS1005" in failure.stderr and "column 25:" in failure.stderr


def test_namespace_await_context_cli(tmp_path):
    path = tmp_path / "namespaces.mts"
    path.write_text("export namespace N.M { const x=await; export const v={await}; export = await load(); }")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    namespace = root["body"][0]["declaration"]
    value, exported, assignment = namespace["body"]["body"]["body"]
    assert value["declarations"][0]["init"] == {"type": "Identifier", "name": "await"}
    prop, = exported["declaration"]["declarations"][0]["init"]["properties"]
    assert prop["shorthand"] and prop["value"]["name"] == "await"
    assert assignment["expression"]["type"] == "AwaitExpression"
    assert assignment["expression"]["argument"]["callee"]["name"] == "load"
    parser = get_pipeline(path)
    for invalid in ["async function f(){namespace N{const x=await;}}",
                    "namespace N{export default await;}", "{await(k); namespace N{const x=await;}}"]:
        with pytest.raises(ValueError):
            parser.parse(invalid)

    path.write_text("export {}; declare namespace N { declare const x:T; await(x); } "
                    "declare function f():number; await(y);")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    inner = root["body"][1]["body"]["body"][1]["expression"]
    assert inner["type"] == "CallExpression" and inner["callee"]["name"] == "await"
    assert root["body"][-1]["expression"] == {"type": "AwaitExpression", "argument": {"type": "Identifier", "name": "y"}}


def test_type_parameter_diagnostic_and_replay_cli(tmp_path):
    path = tmp_path / "params.ts"
    cli = [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]
    for source, code, column in [("({x<1>(){}});", 1139, 5),
                                 ("await; ({x</A>}); export {};", 1109, 6),
                                 ("type F<T extends /* comment */", 1110, 17),
                                 ("({x<T extends>(){}});", 1109, 14),
                                 ("await; type F<T extends>=T; export {};", 1109, 6),
                                 ("type F<T extends /x/ ** b>=T;", 1005, 26)]:
        path.write_text(source)
        result = subprocess.run(cli, text=True, capture_output=True)
        assert result.returncode and f"TS{code}" in result.stderr and f"column {column}:" in result.stderr
    path.write_text("const obj={x<T extends 1, U>(a:U){return a;}};")
    root = json.loads(subprocess.check_output(cli, text=True))
    prop, = root["body"][0]["declarations"][0]["init"]["properties"]
    first, second = prop["value"]["typeParameters"]["params"]
    assert prop["method"] and first["constraint"]["literal"]["raw"] == "1" and second["name"]["name"] == "U"


def test_identifier_escape_diagnostics(tmp_path):
    parser = get_pipeline(tmp_path / "identifier.ts")
    for source, expected in [(r"a\u{61;", (1199, 6, 0)), (r"a\u{61", (1126, 6, 0)),
                             (r"a\u{30;", (1199, 6, 0)), (r"\u{30;", (1127, 0, 0)),
                             (r"obj.#\u0030;", (1127, 4, 1)), (r"await; a\u002d; export {};", (1109, 5, 1))]:
        with pytest.raises(ValueError) as failure:
            parser.parse(source)
        assert (failure.value.code, failure.value.offset, failure.value.length) == expected
    tsx = get_pipeline(tmp_path / "identifier.tsx")
    for source, expected in [(r"<R n\u{30/>", (1199, 9, 0)), (r"<\u0030/>", (1109, 0, 1)),
                             (r"+<\u0030/>", (1127, 2, 0)), (r"<A.B-\u{30/>", (1003, 4, 1))]:
        with pytest.raises(ValueError) as failure:
            tsx.parse(source)
        assert (failure.value.code, failure.value.offset, failure.value.length) == expected
    member = parser.parse(r"obj.#\u0061;")["body"][0]["expression"]
    assert member["property"] == {"type": "PrivateIdentifier", "name": "a"}


def test_unary_power_diagnostics_cli(tmp_path):
    path = tmp_path / "power.ts"
    cli = [sys.executable, "-m", "orionparser", "parse", str(path), "--json"]
    for source, code, column in [("type F<T extends +a ** b>=T;", 17006, 18), ("<T>-x ** b;", 17007, 1),
                                 ("async function f(){return ++await(x) ** y;}", 1109, 29)]:
        path.write_text(source)
        result = subprocess.run(cli, text=True, capture_output=True)
        assert result.returncode and f"TS{code}" in result.stderr and f"column {column}:" in result.stderr
    path.write_text("(-x) ** y ** z;")
    tree = json.loads(subprocess.check_output(cli, text=True))["body"][0]["expression"]
    assert tree["operator"] == "**" and tree["left"]["operator"] == "-"
    assert tree["right"]["operator"] == "**" and tree["right"]["right"]["name"] == "z"


def test_assertion_arithmetic_cli(tmp_path):
    path = tmp_path / "assertion.tsx"
    path.write_text("x + y as Box<T> / /r/.test(z) ** k << 1; a<b>=c; a<b>>>c; f<A<B>>(v);")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    shift = tree["body"][0]["expression"]
    division = shift["left"]
    assertion, power = division["left"], division["right"]
    assert shift["operator"] == "<<" and shift["right"]["raw"] == "1" and division["operator"] == "/"
    assert assertion["type"] == "TSAsExpression" and assertion["expression"]["operator"] == "+"
    assert assertion["typeAnnotation"]["typeName"]["name"] == "Box"
    assert assertion["typeAnnotation"]["typeArguments"]["params"][0]["typeName"]["name"] == "T"
    assert power["operator"] == "**" and power["right"]["name"] == "k"
    assert power["left"]["callee"]["object"]["pattern"] == "r"

    relation, unsigned, generic = [statement["expression"] for statement in tree["body"][1:]]
    assert relation["operator"] == ">=" and relation["left"]["operator"] == "<"
    assert unsigned["operator"] == "<" and unsigned["right"]["operator"] == ">>>"
    argument, = generic["typeArguments"]["params"]
    assert generic["type"] == "CallExpression" and argument["typeArguments"]["params"][0]["typeName"]["name"] == "B"

    path.write_text("a<b>>=c;")
    rejected = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                              capture_output=True, text=True)
    assert rejected.returncode and "TS1005" in rejected.stderr and "column 4:" in rejected.stderr
    parser = get_pipeline(path)
    for source, expected in (("a<b>>>=c;", (1005, 3, 4)), ("a+b\n=c;", (1128, 4, 1)),
                             ("f(a+b\n=c);", (1005, 6, 1)), ("await; a?b+c=d:e; export {};", (1109, 5, 1)),
                             ("await; if(x+y = v; export {}) {};", (1109, 5, 1)),
                             ("await; if(f(x+y = v; export {})) {};", (1109, 5, 1))):
        with pytest.raises(SourceSyntaxError) as failure:
            parser.parse(source)
        assert (failure.value.code, failure.value.offset, failure.value.length) == expected
    shifted = parser.parse("a >>= c;")["body"][0]["expression"]
    assert shifted["type"] == "AssignmentExpression" and shifted["operator"] == ">>="

    path.write_text("[{x:y=1,},,]=[{x:2,},,];")
    node = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))["body"][0]["expression"]
    left, right = node["left"], node["right"]
    assert left["type"] == "ArrayPattern" and right["type"] == "ArrayExpression"
    for array in (left, right):
        obj, hole = array["elements"]
        assert hole is None and array["trailingComma"] and obj["trailingComma"]
    default = left["elements"][0]["properties"][0]["value"]
    assert default["type"] == "AssignmentPattern" and default["left"]["name"] == "y"


def test_unterminated_regexp_and_replay(tmp_path):
    source = "await; async function* f(){type await<T/>;} export {};"
    for filename in ("angle.ts", "angle.tsx"):
        path = tmp_path / filename
        path.write_text(source)
        error = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                               capture_output=True, text=True)
        assert error.returncode and "TS1109" in error.stderr and "column 6:" in error.stderr
    tsx = get_pipeline(tmp_path / "regex.tsx")
    with pytest.raises(ValueError) as failure:
        tsx.parse("<A>{x</A>")
    assert (failure.value.code, failure.value.offset, failure.value.length) == (1005, 5, 2)
    child, = tsx.parse("<A>{x < /r/.test(y)}</A>")["body"][0]["expression"]["children"]
    comparison = child["expression"]
    assert comparison["operator"] == "<" and comparison["right"]["callee"]["object"]["pattern"] == "r"
    parser = get_pipeline(tmp_path / "regex.ts")
    for source, length in [("/𐐀)tail", 2), ("/a(b)c;  }", 6), ("/[x]\\}z]", 7)]:
        with pytest.raises(ValueError) as failure:
            parser.parse(source)
        assert (failure.value.code, failure.value.offset, failure.value.length) == (1161, 0, length)


def test_awaited_regexp_before_namespace_cli(tmp_path):
    path = tmp_path / "replay.ts"
    path.write_text("export {}; await /x/.test(value); namespace N {const x=await;}")
    cli = [sys.executable, "-m", "orionparser"]
    _, stmt, namespace = json.loads(subprocess.check_output([*cli, "parse", str(path), "--json"]))["body"]
    awaited = stmt["expression"]
    assert awaited["type"] == "AwaitExpression"
    call = awaited["argument"]
    assert call["callee"]["object"]["type"] == "RegExpLiteral" and call["callee"]["object"]["pattern"] == "x"
    assert call["arguments"] == [{"type": "Identifier", "name": "value"}]
    assert namespace["body"]["body"][0]["declarations"][0]["init"] == {"type": "Identifier", "name": "await"}
    tokens = json.loads(subprocess.check_output([*cli, "tokens", str(path), "--json"]))
    assert [t["value"] for t in tokens if t["type"] == "REGEXP"] == ["/x/"]
    assert all(t["value"] != "" for t in tokens)
    for invalid in ("await /x/; namespace N{const x=await;}", "export {}; x/; namespace N{const x=await;}",
                    "export {}; await {x:1}; namespace N{const x=await;}"):
        with pytest.raises(ValueError):
            get_pipeline(path).parse(invalid)


def test_regexp_character_range_diagnostics_cli(tmp_path):
    source = r"/*𐐀*/ /[^z-a\d-\s]/u;"
    path = tmp_path / "ranges.ts"
    path.write_text(source, encoding="utf-8")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    literal = tree["body"][0]["expression"]
    assert [(d["code"], source[d["offset"]:d["offset"] + d["length"]]) for d in literal["diagnostics"]] == [
        (1517, "z-a"), (1516, r"\d"), (1516, r"\s")]
    first, second = literal["alternatives"][0][0]["elements"]
    assert first["min"]["value"] == "z" and first["max"]["value"] == "a"
    assert second["min"]["kind"] == "d" and second["max"]["kind"] == "s"


def test_unicode_sets_range_endpoints_cli(tmp_path):
    path = tmp_path / "sets.ts"
    source = r"/*𐐀*/ /[^[[x]&&[y]]-\q{ab|c}]/v;"
    path.write_text(source, encoding="utf-8")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    regex = tree["body"][0]["expression"]
    assert [(d["code"], source[d["offset"]:d["offset"] + d["length"]]) for d in regex["diagnostics"]] == [
        (1516, "[[x]&&[y]]"), (1518, r"\q{ab|c}"), (1516, r"\q{ab|c}")]
    char_range, = regex["alternatives"][0][0]["expression"]["elements"]
    assert char_range["type"] == "CharacterRange"
    assert char_range["min"]["expression"]["type"] == "SetIntersection"
    assert char_range["max"]["alternatives"] == ["ab", "c"]


def test_trailing_unicode_sets_range(tmp_path):
    source = "/[ab-]/v;"
    literal = get_pipeline(tmp_path / "set.ts").parse(source)["body"][0]["expression"]
    a, trailing = literal["alternatives"][0][0]["expression"]["elements"]
    assert a == {"type": "Character", "value": "a"}
    assert trailing == {"type": "CharacterRange", "min": {"type": "Character", "value": "b"}, "max": None}
    assert "diagnostics" not in literal and literal["compatibilityDiagnostics"][0]["offset"] == source.index("-")
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "set.js").parse(source)


def test_unicode_sets_complement_diagnostics_cli(tmp_path):
    path = tmp_path / "complements.ts"
    source = r"/*𐐀*/ [ /[^\q{ab}x]/v, /[^\q{ab}&&\q{c|de}]/v, /[^\q{ab}--[^\q{xy}]]/v ];"
    path.write_text(source, encoding="utf-8")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    union, intersection, subtraction = root["body"][0]["expression"]["elements"]
    for literal, kind, spans in [
        (union, "SetUnion", [r"\q{ab}"]),
        (intersection, "SetIntersection", [r"\q{ab}&&\q{c|de}"]),
        (subtraction, "SetSubtraction", [r"\q{ab}", r"\q{xy}"]),
    ]:
        assert literal["alternatives"][0][0]["expression"]["type"] == kind
        assert [(d["code"], source[d["offset"]:d["offset"] + d["length"]]) for d in literal["diagnostics"]] == [
            (1518, span) for span in spans]
    assert subtraction["alternatives"][0][0]["expression"]["right"]["negate"]


def test_unicode_sets_string_escape_recovery_cli(tmp_path):
    src = r"/*𐐀*/ [/[\q\q{\d|&&|a-b}]/v, /[^\q{!!}]/v];"
    path = tmp_path / "set-strings.ts"
    path.write_text(src, encoding="utf-8")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    recovered, complement = root["body"][0]["expression"]["elements"]
    assert [(d["code"], src[d["offset"]:d["offset"] + d["length"]]) for d in recovered["diagnostics"]] == [
        (1521, r"\q"), (1535, r"\d"), (1522, "&&"), (1508, "-")]
    bare, strings = recovered["alternatives"][0][0]["expression"]["elements"]
    assert bare == {"type": "Character", "value": "q"}
    assert strings["alternatives"] == ["d", "&&", "a-b"] and strings["characterCounts"] == [1, 1, 3]
    assert [d["code"] for d in complement["diagnostics"]] == [1522]


def test_regexp_incomplete_escape_cli(tmp_path):
    src = r"/*𐐀*/ [/[\q{\x1Z|\u{110000}}]/v, /[\u0-z]/u, /[\q{a]/v];"
    path = tmp_path / "escapes.ts"
    path.write_text(src, encoding="utf-8")
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    string, char_range, unclosed = ast["body"][0]["expression"]["elements"]
    issue, limit = string["diagnostics"]
    assert (issue["code"], issue["offset"], issue["length"]) == (1125, src.index("Z"), 0)
    assert (limit["code"], limit["offset"], limit["length"]) == (1198, src.index("110000"), 6)
    strings, = string["alternatives"][0][0]["expression"]["elements"]
    assert strings["alternatives"] == [r"\x1Z", r"\u{110000}"] and strings["characterCounts"] == [2, 1]
    span, = char_range["alternatives"][0][0]["elements"]
    assert span["min"] == {"type": "InvalidEscape", "value": r"\u0"} and span["max"]["value"] == "z"
    group = unclosed["alternatives"][0][0]
    assert group["missingClose"] and group["expression"]["elements"][0]["missingClose"]
    assert [d["code"] for d in unclosed["diagnostics"]] == [1508, 1005, 1005]
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "escapes.js").parse(src)


def test_regexp_quantifier_recovery_cli(tmp_path):
    path = tmp_path / "quantifiers.ts"
    source = "/*𐐀*/ [/a{03,1}?b*/u, /a{,2/u, /a**?/u];"
    path.write_text(source, encoding="utf-8")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    reversed_bounds, incomplete, orphan = root["body"][0]["expression"]["elements"]
    assert [(d["code"], source[d["offset"]:d["offset"] + d["length"]]) for d in reversed_bounds["diagnostics"]] == [(1506, "03,1")]
    first, second = reversed_bounds["alternatives"][0]
    assert first["quantifier"] == "{03,1}" and not first["greedy"] and second["atom"]["value"] == "b"
    assert [(d["code"], d["offset"], d["length"]) for d in incomplete["diagnostics"]] == [
        (1505, source.index(",2"), 0), (1005, source.index("/u", source.index(",2")), 0)]
    assert incomplete["alternatives"][0][0]["quantifier"] == "{,2"
    valid, invalid = orphan["alternatives"][0]
    assert valid["atom"]["value"] == "a" and invalid == {"type": "InvalidQuantifier", "quantifier": "*", "greedy": False}
    assert orphan["diagnostics"][0]["code"] == 1507 and orphan["diagnostics"][0]["length"] == 2


def test_named_capture_diagnostic_spans_cli(tmp_path):
    path = tmp_path / "captures.ts"
    source = r"/*𐐀*/ [/(?<>x)(?<alpha>y)(?<alpha>z)\k<alpa>/u, /\k<later>(?<later>a)/u];"
    path.write_text(source, encoding="utf-8")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    broken, forward = root["body"][0]["expression"]["elements"]
    empty, capture, duplicate, reference = broken["alternatives"][0]
    assert [(g["index"], g["name"]) for g in [empty, capture, duplicate]] == [(1, None), (2, "alpha"), (3, "alpha")]
    assert reference == {"type": "Backreference", "name": "alpa"}
    assert [(d["code"], source[d["offset"]:d["offset"] + d["length"]]) for d in broken["diagnostics"]] == [
        (1514, ""), (1515, "alpha"), (1532, "alpa"), (1369, "alpa")]
    assert broken["diagnostics"][0]["offset"] == source.index(">")
    assert broken["diagnostics"][-1]["suggestion"] == "alpha"
    assert forward["alternatives"][0][0] == {"type": "Backreference", "name": "later"}
    assert "diagnostics" not in forward


def test_regexp_property_spans_cli(tmp_path):
    path = tmp_path / "properties.ts"
    source = r"/*𐐀*/ [/\p{GC=Ll}/u, /[\p{Script=Lati}-x]/u, /\P{RGI_Emoji}/v, /\p{sc=Latin/u];"
    path.write_text(source, encoding="utf-8")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    named, ranged, negative, incomplete = root["body"][0]["expression"]["elements"]
    assert named["alternatives"][0][0]["name"] == "GC" and named["alternatives"][0][0]["value"] == "Ll"
    assert [(d["code"], source[d["offset"]:d["offset"] + d["length"]]) for d in named["diagnostics"]] == [
        (1524, "GC"), (1369, "GC")]
    assert named["diagnostics"][-1]["suggestion"] == "gc"
    left = ranged["alternatives"][0][0]["elements"][0]["min"]
    assert left["type"] == "UnicodePropertyEscape" and left["value"] == "Lati"
    assert [d["code"] for d in ranged["diagnostics"]] == [1526, 1369, 1516]
    assert negative["diagnostics"][0]["code"] == 1518 and negative["alternatives"][0][0]["negate"]
    assert incomplete["alternatives"][0][0]["missingClose"] and incomplete["diagnostics"][0]["length"] == 0


def test_scoped_regexp_modifier_recovery_cli(tmp_path):
    path = tmp_path / "subpattern.ts"
    path.write_text("/(?g-g:x)(?i y)(?-:z)/uu;", encoding="utf-8")
    root = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    literal = root["body"][0]["expression"]
    groups = literal["alternatives"][0]
    assert [d["code"] for d in literal["diagnostics"]] == [1500, 1509, 1509, 1005, 1504]
    assert groups[1]["modifiers"] == {"enable": "i", "disable": "", "missingColon": True}
    assert [a["value"] for a in groups[1]["alternatives"][0]] == [" ", "y"]


def test_mixed_unicode_sets_operators_cli(tmp_path):
    path = tmp_path / "operators.ts"
    source = "/*𐐀*/ [/[a&&b--c]/v, /[a&&]/v, /[--]/v, /[ab&&&c]/v];"
    path.write_text(source, encoding="utf-8")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    mixed, trailing, empty, union = tree["body"][0]["expression"]["elements"]

    def set_expression(literal):
        return literal["alternatives"][0][0]["expression"]

    operation = set_expression(mixed)
    assert operation["type"] == "SetSubtraction" and operation["expectedOperator"] == "&&"
    assert operation["left"]["type"] == "SetIntersection" and operation["right"]["value"] == "c"
    assert [(d["code"], d["offset"], d["length"]) for d in mixed["diagnostics"]] == [(1519, source.index("--"), 2)]
    assert set_expression(trailing)["right"] == {"type": "MissingSetOperand"}
    assert set_expression(empty)["left"] == set_expression(empty)["right"] == {"type": "MissingSetOperand"}
    assert [d["code"] for d in empty["diagnostics"]] == [1520, 1520]
    assert set_expression(union)["elements"][2] == {"type": "InvalidSetOperator", "operator": "&&", "extraAmpersand": True}
    assert [d["code"] for d in union["diagnostics"]] == [1519, 1508]
    for pattern in ("/[a&&b--c]/v", "/[a&&]/v", "/[--]/v", "/[ab&&&c]/v"):
        with pytest.raises(ValueError):
            get_pipeline(tmp_path / "operators.js").parse(pattern)


def test_missing_set_operator_cli(tmp_path):
    path = tmp_path / "missing.ts"
    source = r"/*𐐀*/ /[a&&bc\q]/v;"
    path.write_text(source, encoding="utf-8")
    ast = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    regex = ast["body"][0]["expression"]
    assert [(d["code"], d["offset"], d["length"]) for d in regex["diagnostics"]] == [
        (1005, source.index("c"), 0), (1005, source.index("\\"), 0), (1521, source.index("\\"), 2)]
    expr = regex["alternatives"][0][0]["expression"]
    assert expr["missingOperator"] and expr["type"] == "SetIntersection" and expr["right"]["value"] == "q"
    assert expr["left"]["missingOperator"] and expr["left"]["right"]["value"] == "c"
    assert expr["left"]["left"]["right"]["value"] == "b"
    with pytest.raises(ValueError):
        get_pipeline(tmp_path / "missing.js").parse(source)


def test_contextual_statement_start_cli(tmp_path):
    path = tmp_path / "starts.ts"
    path.write_text("public\nfunction f(){}\nif (ok) defer + x;")
    tree = json.loads(subprocess.check_output([sys.executable, "-m", "orionparser", "parse", str(path), "--json"]))
    first, function, conditional = tree["body"]
    assert first["expression"] == {"type": "Identifier", "name": "public"}
    assert function["type"] == "FunctionDeclaration" and function["id"]["name"] == "f"
    expr = conditional["consequent"]["expression"]
    assert expr["type"] == "BinaryExpression" and expr["left"]["name"] == "defer" and expr["right"]["name"] == "x"
    with pytest.raises(ValueError):
        get_pipeline(path).parse("public x;")


def test_invalid_contextual_statement_start_diagnostics_cli(tmp_path):
    path = tmp_path / "statements.ts"
    source = "/*𐐀*/\r\nswitch(k){case 1: readonly value;}"
    path.write_bytes(source.encode("utf-8"))
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            capture_output=True, text=True)
    assert result.returncode and "line 2, column 19:" in result.stderr and "TS1129" in result.stderr
    parser = get_pipeline(path)
    for text, code in [("public x;", 1128), ("public in rhs;", 1128), ("if(ok) public x;", 1434)]:
        with pytest.raises(ValueError, match=f"TS{code}") as failure:
            parser.parse(text)
        assert failure.value.offset == text.index("public")
    expr = parser.parse("if(ok) public in rhs;")["body"][0]["consequent"]["expression"]
    assert expr["operator"] == "in" and expr["left"]["name"] == "public"


def test_statement_keyword_suggestion_cli(tmp_path):
    path = tmp_path / "keyword.ts"
    for spelling, suggestion in [("fuction", "function"), ("constvariable", "const variable")]:
        source = f"/*𐐀*/ {spelling} value;"
        path.write_text(source, encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                                capture_output=True, text=True)
        assert result.returncode and "TS1435" in result.stderr and f"'{suggestion}'" in result.stderr
        assert "line 1, column 7:" in result.stderr
    with pytest.raises(ValueError, match="TS1260") as rejected:
        get_pipeline(path).parse(r"p\u0075blic class C{}")
    assert rejected.value.offset == 0
    statements = get_pipeline(path).parse(r"d\u0065clare x;")["body"]
    assert [s["expression"]["name"] for s in statements] == ["declare", "x"]


def test_tagged_template_missing_semicolon_cli(tmp_path):
    path = tmp_path / "tag.ts"
    template = "`outer\r\n${inner`𐐀`}tail`"
    source = "throw tag<T> /*𐐀*/ " + template + " next;"
    path.write_bytes(source.encode("utf-8"))
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            capture_output=True, text=True)
    assert result.returncode and "TS1443" in result.stderr
    with pytest.raises(ValueError) as rejected:
        get_pipeline(path).parse(source)
    err = rejected.value
    assert (err.code, err.offset, err.length) == (1443, source.index(template), len(template))
    statements = get_pipeline(path).parse("tag`𐐀`\r\nnext;")["body"]
    assert statements[0]["expression"]["type"] == "TaggedTemplateExpression"
    assert statements[1]["expression"] == {"type": "Identifier", "name": "next"}
    for ordinary in ["(tag`x`) next;", "let t=tag`x` next;", "x+tag`x` next;"]:
        with pytest.raises(ValueError) as invalid:
            get_pipeline(path).parse(ordinary)
        assert invalid.value.code != 1443 and invalid.value.offset == ordinary.index("next")


def test_class_field_separator_diagnostics_cli(tmp_path):
    path = tmp_path / "field.ts"
    parser = get_pipeline(path)
    for body, code, target in [
        ("𐐀:T /*gap*/ next", 1442, "next"), ("x:T\r\n()", 1441, "("), ("x @dec y", 1436, "@"),
        ("x:T=1 next", 1005, "next"), ("𐐀 next", 1434, "𐐀"), ("[key] next", 1005, "next"),
    ]:
        source = "class C{" + body + "}"
        with pytest.raises(ValueError) as rejected:
            parser.parse(source)
        assert (rejected.value.code, rejected.value.offset, rejected.value.length) == (
            code, source.index(target), len(target))
    path.write_bytes("class C{𐐀:T\r\n() }".encode("utf-8"))
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            capture_output=True, text=True)
    assert result.returncode and "line 2, column 1:" in result.stderr and "TS1441" in result.stderr
    first, other = parser.parse("class C{x:T\n@dec y}")["body"][0]["body"]["body"]
    assert first["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "T"
    assert other["key"]["name"] == "y" and other["decorators"][0]["expression"]["name"] == "dec"


def test_tsx_typed_parent_closing_tag_cli(tmp_path):
    path = tmp_path / "view.tsx"
    path.write_text("<UI.Root<T>>\n  <UI.Child<U>>\n</UI.Root>")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True)
    assert result.returncode and "line 2, column 4:" in result.stderr and "TS17008" in result.stderr
    path.write_text("<UI.Root<T>><UI.Child<U>></UI.Child></UI.Root>")
    root = get_pipeline(path).parse(path.read_text())["body"][0]["expression"]
    child, = root["children"]
    assert child["closingElement"]["name"] == child["openingElement"]["name"]
    assert root["closingElement"]["name"] == root["openingElement"]["name"]
    assert child["openingElement"]["typeArguments"]["params"][0]["typeName"]["name"] == "U"


def test_tsx_missing_closing_tag_at_eof_cli(tmp_path):
    path = tmp_path / "unfinished.tsx"
    path.write_text("const x = <Outer>\n  <  UI.Inner<T>>text")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True)
    assert result.returncode and "line 2, column 6:" in result.stderr and "TS17008" in result.stderr
    for source, code, offset, length in [
        ("const x = /*c*/ <>text", 17014, 9, 9), ("<A><   B<T>></B>", 17008, 1, 1),
        ("<A></  ", 1003, 5, 0), ("<></  ", 17015, 6, 0), ("<A x=", 1145, 5, 0),
    ]:
        with pytest.raises(ValueError) as failure:
            get_pipeline(path).parse(source)
        assert (failure.value.code, failure.value.offset, failure.value.length) == (code, offset, length)


def test_tsx_attribute_hex_escape_position_cli(tmp_path):
    path = tmp_path / "escape.tsx"
    path.write_text(r'<A value= "\xZ"/>')
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True)
    assert result.returncode and "TS1125" in result.stderr and "line 1, column 14:" in result.stderr
    path.write_text(r'<A value="\xZ"/>')
    element = get_pipeline(path).parse(path.read_text())["body"][0]["expression"]
    assert element["openingElement"]["attributes"][0]["value"]["value"] == r"\xZ"


def test_nested_template_errors_and_eof(tmp_path):
    path = tmp_path / "nested.ts"
    parser = get_pipeline(path)
    for source, code, offset, length in [
        (r"`bad\xZ${`inner\u{}`}tail`", 1125, 6, 0),
        (r"tag`bad\xZ${`inner\u{}`}tail`", 1125, 21, 0),
        (r"`h${X}bad\8", 1488, 9, 2),
        (r"tag`h${X}bad\8", 1160, 14, 0),
        ("type T = `h${  ", 1110, 13, 0),
    ]:
        with pytest.raises(ValueError) as failure:
            parser.parse(source)
        assert (failure.value.code, failure.value.offset, failure.value.length) == (code, offset, length)


def test_template_type_rejects_call_at_open_parenthesis_cli(tmp_path):
    path = tmp_path / "call.ts"
    path.write_text("type T = `h${F(x)}`;")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True)
    assert result.returncode and "TS1005" in result.stderr and "line 1, column 15:" in result.stderr
    path.write_text("const t = `h${F(x)}`;")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True, check=True)
    expression, = json.loads(result.stdout)["body"][0]["declarations"][0]["init"]["expressions"]
    assert expression["type"] == "CallExpression" and expression["callee"]["name"] == "F"
    assert [argument["name"] for argument in expression["arguments"]] == ["x"]


def test_reference_diagnostic_precedence_and_span(tmp_path):
    path = tmp_path / "refs.ts"
    first = '/// <reference path="a"/>'
    module = '/// <amd-module name="foo"/>'
    invalid = '/// <reference types="𐐀pkg" resolution-mode="bad"/>'
    for lines, code, marker, length in [
        ([first, module, module, invalid], 1453, "𐐀pkg", 4),
        ([module, first, invalid, module], 2458, module, len(module)),
        ([invalid, "throw ;"], 1109, ";", 1),
    ]:
        source = "\r\n".join(lines)
        with pytest.raises(ValueError) as rejected:
            get_pipeline(path).parse(source)
        error = rejected.value
        assert (error.code, error.offset, error.length) == (code, source.rindex(marker), length)


def test_reserved_type_list_start_and_comparison_cli(tmp_path):
    path = tmp_path / "list.ts"
    path.write_text("class C extends B { m(){return f<super.x>(a);} }")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True, check=True)
    method, = json.loads(result.stdout)["body"][0]["body"]["body"]
    expression = method["value"]["body"]["body"][0]["argument"]
    assert expression["type"] == "BinaryExpression" and expression["operator"] == ">"
    less = expression["left"]
    assert less["operator"] == "<" and less["right"]["object"]["type"] == "Super"
    assert less["right"]["property"]["name"] == "x"
    parser = get_pipeline(path)
    for source, code, token in [
        ("type X=Box<super.x>;", 1005, "super"), ("type X=[T,return.x];", 1110, "return"),
        ("type X=T[((super.x))];", 1005, "("), ("function* f(){x + yield;}", 1109, "yield"),
    ]:
        with pytest.raises(ValueError) as failure:
            parser.parse(source)
        assert (failure.value.code, failure.value.offset, failure.value.length) == (code, source.index(token), len(token))
    named = parser.parse("type X=super.x;")["body"][0]["typeAnnotation"]["typeName"]
    assert named["left"]["name"] == "super" and named["right"]["name"] == "x"


def test_function_type_readonly_let_parameter_cli(tmp_path):
    path = tmp_path / "signature.d.mts"
    path.write_text("export type F=(readonly let:T)=>R;")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True, check=True)
    signature = json.loads(result.stdout)["body"][0]["declaration"]["typeAnnotation"]
    parameter, = signature["params"]
    assert (signature["type"], parameter["name"], parameter["modifiers"]) == ("TSFunctionType", "let", ["readonly"])
    assert parameter["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "T"


def test_parameter_decorator_after_export_cli(tmp_path):
    path = tmp_path / "constructor.ts"
    path.write_text("class C{constructor(@before export default @after readonly x:T){}}")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True, check=True)
    method, = json.loads(result.stdout)["body"][0]["body"]["body"]
    param, = method["value"]["params"]
    assert param["name"] == "x" and param["modifiers"] == ["export", "default", "readonly"]
    assert [(d["expression"]["name"], d["modifierIndex"]) for d in param["decorators"]] == [
        ("before", 0), ("after", 2),
    ]
    invalid = "class C{constructor(export @a export @b x:T){}}"
    with pytest.raises(ValueError) as failure:
        get_pipeline(path).parse(invalid)
    assert (failure.value.code, failure.value.offset, failure.value.length) == (1003, invalid.index("@b"), 1)


def test_escaped_type_keyword_and_speculative_call_cli(tmp_path):
    path = tmp_path / "escape.ts"
    path.write_text(r"type X = \u0074rue;")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True)
    assert result.returncode and "TS1260" in result.stderr and "line 1, column 10:" in result.stderr
    parser = get_pipeline(path)
    for src in (r"type T=n\u0075mber;", r"f<n\u0075mber>(x);"):
        with pytest.raises(ValueError) as failure:
            parser.parse(src)
        assert (failure.value.code, failure.value.offset, failure.value.length) == (1260, src.index("n\\"), 11)
    alias, statement = parser.parse(r"type X=NS.\u0074rue; f<n\u0075mber>+x;")["body"]
    assert alias["typeAnnotation"]["typeName"]["right"]["name"] == "true"
    comparison = statement["expression"]
    assert comparison["operator"] == ">" and comparison["left"]["operator"] == "<"


def test_escaped_let_for_initializer_cli(tmp_path):
    path = tmp_path / "loop.ts"
    path.write_text(r"for (\u006cet of xs) {}")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            capture_output=True, text=True)
    assert result.returncode and "TS1260" in result.stderr and "line 1, column 6:" in result.stderr
    parser = get_pipeline(path)
    loop, expr = parser.parse(r"for (let of xs) {} obj.\u006cet;")["body"]
    assert loop["type"] == "ForOfStatement" and loop["left"]["kind"] == "let"
    assert expr["expression"]["property"]["name"] == "let"


def test_multiline_await_using_cli(tmp_path):
    path = tmp_path / "resources.ts"
    path.write_text("await\nusing let = open();\nfor (await /*𐐀\n*/ using item of items) consume(item);")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            capture_output=True, text=True, check=True)
    declaration, loop = json.loads(result.stdout)["body"]
    assert declaration["kind"] == loop["left"]["kind"] == "await using"
    assert declaration["declarations"][0]["id"]["name"] == "let"
    assert loop["type"] == "ForOfStatement" and loop["right"]["name"] == "items"


def test_class_keyword_line_boundaries_cli(tmp_path):
    path = tmp_path / "members.ts"
    path.write_text("class C{" + r"\u0073tatic" + "\nx:T;}")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True)
    assert result.returncode and "TS1260" in result.stderr and "line 1, column 9:" in result.stderr
    path.write_text("class C{static\nx:T; async!:T; get\n*g(){} export\n@d readonly field:T;}")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True, check=True)
    static, definite, field, generator, decorated = json.loads(result.stdout)["body"][0]["body"]["body"]
    assert static["key"]["name"] == "x" and static["static"]
    assert definite["key"]["name"] == "async" and definite["definite"]
    assert field["type"] == "PropertyDefinition" and field["key"]["name"] == "get"
    assert generator["key"]["name"] == "g" and generator["value"]["generator"]
    assert decorated["modifiers"] == ["export", "readonly"]
    assert [(d["modifierIndex"], d["expression"]["name"]) for d in decorated["decorators"]] == [(1, "d")]


def test_async_decorated_class_prefix_order(tmp_path):
    parser = get_pipeline(tmp_path / "order.ts")
    cls = parser.parse("class C{static async export @d m(){return await f()}}")["body"][0]
    method, = cls["body"]["body"]
    assert method["modifiers"] == ["static", "async", "export"]
    assert method["static"] and method["value"]["async"]
    assert method["decorators"][0]["modifierIndex"] == 3
    result, = method["value"]["body"]["body"]
    assert result["argument"]["type"] == "AwaitExpression"
    source = "class C{@a export @b export @c x:T;}"
    with pytest.raises(ValueError) as rejected:
        parser.parse(source)
    assert (rejected.value.code, rejected.value.offset, rejected.value.length) == (1146, source.index(" @c"), 0)


def test_static_block_with_preceding_modifiers_cli(tmp_path):
    path = tmp_path / "blocks.ts"
    path.write_text("class C{static static {run(x);} static async export @d static {use(y);}}")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True, check=True)
    first, second = json.loads(result.stdout)["body"][0]["body"]["body"]
    assert first["type"] == second["type"] == "StaticBlock"
    assert first["modifiers"] == ["static"] and second["modifiers"] == ["static", "async", "export"]
    assert second["decorators"][0]["modifierIndex"] == 3
    assert [block["body"][0]["expression"]["callee"]["name"] for block in (first, second)] == ["run", "use"]


def test_modified_class_index_signature_cli(tmp_path):
    path = tmp_path / "index.ts"
    path.write_text("class C{static async export @d [k:string]:T; async [cond ? x : y]:T;}")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True, check=True)
    signature, field = json.loads(result.stdout)["body"][0]["body"]["body"]
    assert signature["type"] == "TSIndexSignature" and signature["typeAnnotation"]["typeAnnotation"]["typeName"]["name"] == "T"
    key, = signature["parameters"]
    assert key["name"] == "k" and key["typeAnnotation"]["typeAnnotation"]["type"] == "TSStringKeyword"
    assert signature["modifiers"] == ["static", "async", "export"] and signature["decorators"][0]["modifierIndex"] == 3
    assert field["type"] == "PropertyDefinition" and field["key"]["type"] == "ConditionalExpression"


def test_module_first_diagnostic_cli(tmp_path):
    path = tmp_path / "replay.ts"
    for source, offset in [
        ("export {}; await; throw;", 16),
        ("await; throw; export {};", 5),
        ("await; const = 1; export {};", 5),
        ("await; ({x:}); export {};", 5),
        ("await; ({#x}); export {};", 5),
        ("await; type T={x:}; export {};", 5),
        ("await; function f(if){} export {};", 5),
        ("await; throw;", 12),
        ("namespace N{export {};} await; throw;", 36),
    ]:
        path.write_text(source)
        result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                                text=True, capture_output=True)
        assert result.returncode and "TS1109" in result.stderr and f"line 1, column {offset + 1}:" in result.stderr


def test_missing_declarator_preserves_script_diagnostic(tmp_path):
    parser = get_pipeline(tmp_path / "binding.ts")
    for source, token, code in [
        ("const = 1;", "=", 1134), ("var a, /*𐐀*/ = v;", "=", 1134), ("const :T=1;", ":", 1134),
        ("const default=0;", "default", 1389), ("function f(if){}", "if", 1390),
        ("function f(in){}", "in", 1359), ("function f(,){}", ",", 1138), ("f(,);", ",", 1135),
        ("({,x:1});", ",", 1136), ("({x:});", "}", 1109), ("const {x:}=v;", "}", 1003),
        ("({#x /*𐐀*/ });", "}", 1005), ("({[x] = v});", "=", 1005),
        ("type T={x:};", "}", 1110), ("[x + ];", "]", 1109),
    ]:
        with pytest.raises(ValueError) as failure:
            parser.parse(source)
        assert (failure.value.code, failure.value.offset, failure.value.length) == (code, source.index(token), len(token))
    assignment, = parser.parse("let = 1;")["body"]
    assert assignment["expression"]["type"] == "AssignmentExpression"
    assert assignment["expression"]["left"]["name"] == "let"


def test_for_of_declaration_lookahead_scope_cli(tmp_path):
    path = tmp_path / "loop.ts"
    path.write_text("export {}; for (let of yield) {}")
    result = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                            text=True, capture_output=True, check=True)
    root = json.loads(result.stdout)
    loop = root["body"][1]
    assert root["sourceType"] == "module" and loop["type"] == "ForOfStatement"
    assert loop["left"]["kind"] == "let" and loop["left"]["declarations"] == []
    assert loop["right"] == {"type": "Identifier", "name": "yield"}
    source = "function* f(){for (let of yield) {}}"
    path.write_text(source)
    failure = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                             text=True, capture_output=True)
    assert failure.returncode and "TS1005" in failure.stderr and f"column {source.index('yield') + 1}:" in failure.stderr


def test_decorated_resource_declaration_cli(tmp_path):
    path = tmp_path / "resource.ts"
    path.write_text("export @d using\n[x]:T=open(); @e using; public await\nusing item=open();")
    out = subprocess.run([sys.executable, "-m", "orionparser", "parse", str(path), "--json"],
                         capture_output=True, text=True, check=True)
    exported, empty, deferred = json.loads(out.stdout)["body"]
    declaration = exported["declaration"]
    assert declaration["kind"] == empty["kind"] == "using"
    assert declaration["decorators"][0]["modifierIndex"] == 1
    binding, = declaration["declarations"]
    assert binding["id"]["type"] == "ArrayPattern" and binding["id"]["elements"][0]["name"] == "x"
    assert empty["declarations"] == [] and empty["decorators"][0]["expression"]["name"] == "e"
    assert deferred["kind"] == "await using" and deferred["modifiers"] == ["public"]
