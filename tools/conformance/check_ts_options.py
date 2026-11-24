"""Compare tsconfig-driven parsing and module classification with TypeScript 5.9.3."""
import argparse
import json
from pathlib import Path
import tarfile
import tempfile

from check_typescript import COMPILER_SHA, SOURCE_SHA, check_pin, run_compiler, test_units
from orionparser.languages.typescript.options import SyntaxOptions
from orionparser.registry import get_pipeline


_MATRIX = [
    ("file.ts", "let eval=1;", {}),
    ("file.ts", "let eval=1;", {"strict": True, "alwaysStrict": None}),
    ("file.ts", "const 𐐀=1;", {"target": None}),
    ("view.tsx", "<C/>", {"jsx": None, "module": None, "moduleDetection": None}),
    ("file.ts", "let eval=1;", {"alwaysStrict": True}),
    ("file.ts", "let eval=1;", {"alwaysStrict": False, "strict": True}),
    ("file.ts", "let eval=1;", {"moduleDetection": "force"}),
    ("file.ts", "const n=0;", {"module": "nodenext"}),
    ("v.tsx", "const x=<span/>;", {"jsx": "preserve"}),
    ("v.tsx", "const x=<span/>;", {"jsx": "react-jsx"}),
    ("v.tsx", "const x=<span/>;", {"jsx": "react-jsxdev"}),
    ("v.tsx", "const x=<span/>;", {"jsx": "react-jsx", "moduleDetection": "legacy"}),
    ("m.d.mts", "declare const n: unknown;", {"moduleDetection": "force"}),
    ("m.mts", "const x=<T>(v:T)=>v;", {"module": "nodenext"}),
    ("body.ts", "with(o){}; delete x;", {}),
    ("body.ts", "with(o){}; delete x;", {"alwaysStrict": True}),
    ("body.ts", "with(o){}; delete x;", {"moduleDetection": "force"}),
    ("body.ts", '"𐐀"; "use strict"; with (o) {} delete /*name*/ x; delete (y);', {}),
    ("body.ts", 'function f(){"use strict";with(o){} delete x;} delete z;', {}),
    ("body.ts", "class C {f(){with(o){} delete x;}} delete z;", {}),
    ("body.ts", "export {}; delete x; with (o) { delete p.x; }", {}),
    ("name.ts", 'function eval(arguments){"use strict";var eval;arguments++;} eval+=1;', {}),
    ("name.ts", 'function eval(arguments){"use strict";var eval;arguments++;} eval+=1;', {"alwaysStrict": True}),
    ("name.ts", 'export {}; class eval {f(arguments:T){++eval}} function arguments(eval:T){}', {}),
    ("name.ts", '"𐐀";"use strict"; let {x:[arguments],eval,...r}=v;try{}catch(eval:T){}', {}),
    ("name.ts", r'export {}; let \u0065val!:T; ++arguments; (eval)=1; ++(arguments);', {}),
    ("name.ts", 'export declare function eval(arguments:T):T; export declare const arguments:T;', {}),
    ("name.d.ts", 'export function eval(arguments:T):T; export const eval:T;', {}),
    ("name.ts", 'namespace N {"use strict"; let arguments; function f(eval){} } var eval;', {}),
    ("name.ts", '"use strict";interface I{f(eval:T):T} type A=(arguments:T)=>void;', {}),
    ("name.ts", 'export {}; const f=({eval}, ...arguments)=>eval; for(eval of xs){}; ({eval}=x);', {}),
    ("name.ts", 'export {}; const o={eval(){}, [arguments](){}, get arguments(){}}; o.eval++;', {}),
    ("name.ts", 'export {}; function f({arguments}:T){try{}catch({eval}){}}', {}),
    ("name.ts", 'namespace N {"use strict"; with(o){} delete x;} delete y;', {}),
    ("name.ts", 'function f(a=delete x){"use strict";delete y;}', {}),
    ("name.ts", 'function f(){class eval {field=arguments;static {arguments;} }}', {}),
    ("accessor.ts", 'interface I { get x(eval=1){"use strict"; eval++; with(o){} } }', {"target": "es2016"}),
    ("accessor.ts", 'export type I = { set x([eval]?:T){ arguments++; } }', {}),
    ("throw.ts", '"𐐀"; throw /* first\n second */ value;', {}),
    ("throw.ts", 'function f(){throw\n} throw\n;', {}),
    ("throw.ts", 'throw\n', {}),
    ("throw.ts", 'throw new Error();', {}),
    ("throw.ts", 'throw;', {}),
    ("throw.d.ts", 'throw\nvalue', {}),
    ("throw.ts", 'declare namespace N {throw\nvalue;}', {}),
    ("catch.ts", 'try{}catch({a} = /*𐐀*/ ((make()).v)){}', {}),
    ("catch.ts", 'try{}catch([x]: unknown = foo()){} finally {}', {}),
    ("catch.ts", 'export {}; try{}catch(eval = arguments++){}', {}),
    ("catch.ts", 'try{}catch(e!:any=1){}', {}),
    ("optional.ts", 'function f(...[a]?:T){} function g({a}?:T={}){}', {}),
    ("optional.ts", 'class C {constructor(public {a}?:T){}}', {}),
    ("optional.ts", 'function f(@d {a}?:T){}', {"experimentalDecorators": True}),
    ("optional.ts", 'const f=(/*𐐀*/[x]?:T)=>x; const g=async <T>({a}?:T)=>a;', {}),
    ("optional.ts", 'function f([x]?:T); function f([x]?:T){"use strict"}', {"target": "es2016"}),
    ("optional.ts", 'interface I { f({a}?:T):T; } type F=([x]?:T)=>T;', {}),
    ("generic.ts", "function f< /*𐐀*/ >(){} class C<> extends B<> {} interface I<> extends B<> {} type T<>=A<>;", {}),
    ("generic.tsx", "const x=<C<T,>/>; f?.<>(); f<T,>(x); import<>(x); tag<>`q`; obj?.<>`q`;", {}),
    ("generic.ts", "class A<> extends X<> extends Y<> {} class B<> extends P, Q<> {}", {}),
    ("generic.ts", "interface I implements Bad<> {} class C<> implements A<> extends B<> {}", {}),
    ("generic.ts", "type F=new<>()=>T; interface I{m<>():T}; class C{static constructor<>(){}}", {}),
    ("params.ts", "function f(@d ...x:T[],y:T){}; function g(a?:T, /*𐐀*/ {x,y}:T){}", {}),
    ("params.ts", r"function f(public \u0061?:T=1){}; function g(a?,\u0062:T){}", {}),
    ("params.ts", "function f(... /*gap*/ [x]:T=ys,){}; declare function g(...xs? = []):void;", {}),
    ("params.tsx", "const f=(a?:T,b:U)=>b; type G=(...a:T[], b:T)=>T;", {}),
    ("params.ts", "function f(x, ...xs:number[],){}; function g(x,){}", {}),
    ("params.ts", "declare function f(...xs:T[],):void; declare namespace N{function g(...x,):void;}", {}),
    ("params.d.ts", "export function f(...xs:T[],):void;", {}),
    ("params.tsx", "const f=async <T,>(x:T,)=>x; const g=(...xs,)=>xs;", {}),
    ("params.ts", "type F=(...x,)=>void; type G=new(...x,)=>F; interface I{f(...x,):void}", {}),
    ("params.ts", "function f(...x,...y,){}; function g<>(...x,){}; function h(a?, b, ...c,){}", {}),
    ("params.ts", "interface I{private m(...x,):void} class C{readonly m(...x,){} static private n(...y,){} }", {}),
    ("params.ts", "class C{async get x(...a,){}}; const o={private m(...x,){}, async get y(...v,){}};", {}),
    ("params.ts", "@d function decorated(...x,){} declare async function f(...xs, y):void;", {}),
    ("params.ts", "class C{abstract m(...x,):void; declare f:(...x,)=>void;} abstract class D{abstract m(...x,):void;}", {}),
    ("index.ts", "interface I { readonly []:Box<T> /*gap*/; [k:(string|symbol)]; [a:string,b:number]:T }", {}),
    ("index.ts", "type I={ [public key:string]:T; [𐐀,]:T; [k?:number]:T; [key:string=1]:T }", {}),
    ("index.ts", "interface I{static [x:string,]:T} class C{readonly static [k:string,]:T;}", {}),
    ("index.ts", "class C{static readonly [k:string,]:T;} type I={readonly [k:string,]:T};", {}),
    ("params.ts", "declare interface I{[...k:string[],]:T}; interface J{[a:string,b:string,]:T}", {}),
    ("lines.ts", "const f=x=>y\n=>x+y; const g=(a,b) /*𐐀\r\n*/ => a;", {}),
    ("lines.tsx", "const f=async <T,>(x:T):T\n=>x;", {}),
    ("lines.mts", "const f=<T>(x=1)\n=>{'use strict';};", {"target": "esnext"}),
    ("lines.cts", "const f=<T>(x?:T,y:T)\n=>y;", {}),
    ("lines.ts", "const f=(...xs,y)\n=>xs; const g=(x=1)=>{'use strict';};", {"target": "es2016"}),
    ("strict.ts", 'function f(a=1){"use strict"}', {"target": "es2015"}),
    ("strict.ts", 'function f(a=1){"use strict"}', {"target": "es2016"}),
    ("strict.ts", 'function f(a=1){"use strict"}', {"module": "node16"}),
    ("strict.ts", 'function f(a=1){"use strict"}', {}),
    ("strict.ts", 'class C {constructor(public x=1,{a}: A,...r:T[]){"use strict"}}', {}),
    ("strict.ts", 'const f=(/*𐐀*/[a]=[], b:T=1):T=>{"x"; "use strict"; "use strict"}', {}),
    ("strict.ts", r'function f(x=1){"use\x20strict"; with(o){}}', {}),
    ("strict.ts", 'function f(x=1){("use strict");} function g({x}){0;"use strict"}', {}),
    ("strict.ts", 'const f=async <T>(x=1)=>{"use strict"};', {}),
    ("strict.ts", 'function f(x?:T,y=1,z:T){"use strict"}', {}),
    ("strict.ts", 'function f(...x:T[],y=1){"use strict"}', {}),
    ("m.cts", "const x=<T>v;", {"module": "nodenext"}),
    ("m.mts", "const x=<T,>(v:T)=>v;", {"module": "nodenext"}),
    ("m.cts", "const x=async <T = number>(v:T)=>v;", {}),
    ("m.mts", "const x=<T extends number>(v:T)=>v;", {}),
    ("m.ts", "const x=<T>(v:T)=>v;", {}),
    ("generic.d.mts", "const x=<T>(v:T)=>v;", {}),
    ("assert.d.cts", "const x=<T>v;", {}),
    ("offset.mts", 'const text="𐐀"; const f=< /* type */ const T=number>(v:T)=>v;', {}),
]
# The binder visits names in the surrounding scope before it processes a
# function's directive prologue. Repeat these trees in all three contexts.
_STRICT_NAMES = [
    'function eval(arguments:T):T;',
    'class eval { m(eval:T):T; }',
    'abstract class C {abstract f(eval:T):T;}',
    'declare class C {f({eval}:T):T;}',
    'declare namespace N {function eval(arguments:T):T; const arguments:T;}',
    'const C=class arguments{static f(eval:T){}};',
    'const f=async (eval:T)=>eval;',
    'const f=<T>(eval:T)=>eval;',
    'type T={new(eval:U):V; [arguments:string]:T;};',
    'function f(eval=()=>arguments){function g(arguments){}}',
    'class C<T extends (arguments:T)=>T> {}',
    'function f({[eval]:arguments=1,...eval}){}',
    'const x={eval}; const y=arguments; label: for(;;)break label;',
    'let f=(arguments /*x*/ => arguments);',
    'function f(){class C{field=()=>arguments;}}',
    'function f(eval:T){"use strict"; eval++;}',
    'function f(a=eval++){"use strict";}',
    'class C{ [(() => {let eval;})()](){} }',
    'class C extends (function eval(arguments){}) {}',
    'const f=(eval=arguments++)=>{"use strict";eval++};',
    'let {z: [eval = arguments++], ...arguments}=x;',
    'function f({eval}=v){}',
    'function f(): asserts eval {}',
    'import {x as eval} from "a";',
    'type Q = typeof eval;',
    'interface T<eval>{f(eval:T):T}',
    'type T=(this:A, eval?:B)=>void;',
    'declare function f({eval,...arguments}:T):T;',
]
_DIAGNOSTIC_CODES = [1009, 1097, 1098, 1099, 1172, 1173, 1174, 1175, 1176, 1013, 1014, 1015, 1016, 1017, 1018, 1019, 1020, 1021, 1022, 1025, 1047, 1048, 1096, 1100, 1101, 1102, 1197, 1200, 1210, 1215, 1346, 1347, 2463, 7059, 7060]
_ORACLE = """
const ts = require(process.argv[1]), path = require('node:path');
const cases = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const results = cases.map(({name, options, codes}) => {
    const o = ts.convertCompilerOptionsFromJson({...options, noLib:true, noEmit:true}, path.dirname(name));
    if (o.errors.length) throw new Error('Bad matrix options');
    const program = ts.createProgram([name], o.options), file = program.getSourceFile(name);
    const parse = program.getSyntacticDiagnostics(file).map(d=>d.code);
    const diagnostics = program.getSemanticDiagnostics(file);
    const checker = diagnostics.map(d=>d.code);
    const located = diagnostics.filter(d => codes.includes(d.code))
        .map(d => [d.code, Array.from(file.text.slice(0, d.start)).length]);
    const missing = [];
    function visit(n) {
        if (ts.isThrowStatement(n) && n.expression.pos === n.expression.end)
            missing.push(Array.from(file.text.slice(0, n.expression.pos)).length);
        ts.forEachChild(n, visit);
    }
    if (!parse.length) visit(file);
    return {module: ts.isExternalModule(file), parse, checker, located, missing};
});
process.stdout.write(JSON.stringify(results));
"""


def parameter_grammar_cases():
    owners = (("const f=(", ")=>0"), ("const f=async (", ")=>0"), ("const f=<T,>(", "):T=>v"),
              ("function f(", "){}"), ("interface I{m(", "):R}"), ("type F=(", ")=>R;"),
              ("type O={(", "):R}"), ("class C{constructor(", "){}}"), ("class C{m(", "){}}"),
              ("const o={m(", "){}}"), ("function outer(){function f(", "){} }"),
              ("declare namespace N{function f(", "):V;}"))
    parameters = ("x,", "...x,", "a?,b", "a?=x", "...a?,", "...a=x,", "...a,b,", "...a?:T=v,",
                  "{x}?,[y]:T", "@d ...xs,y", "a?, b=v,...r?,", "a?,{x}=v,", "...{x} = v", "a?:T,b=1,c?:T,d:T")
    for prefix, suffix in owners:
        for params in parameters:
            yield "parameter-grammar.ts", prefix + params + suffix, {"target": "esnext"}


def generic_grammar_cases():
    owners = ("function f$(){}", "class C$ {}", "class C$ extends B$ {}", "class C$ extends B, D$ {}",
              "class C$ extends B$, {}", "class C$ implements B$, {}", "class C$ implements I extends J$ {}",
              "class C$ extends B$ extends D$ {}", "interface I$ extends B$ {}", "interface I$ extends B$, D$ {}",
              "type T$=Box$;", "interface I{m$():T}", "class C{m$(){}}", "const o={m$(){}}",
              "const x=class$ {};", "type F=new$()=>T;", "type F=$()=>T;", "f$();", "(f$)();",
              "f?.$();", "new C$();", "tag$`s`;", "x?.t$`s`;", "import$;", "import$();", "import.defer$();",
              "import.defer$;", "const v=<C$/>;", "type F=typeof x$;", 'type F=import("p").X$;',
              "class C{constructor$(){}}", "class C{static constructor$(){}}", "class C{@d m$():void;}",
              "@d class C$ {}", "@d function f$(){}")
    for owner in owners:
        filename = "generic-grammar.tsx" if "<C" in owner else "generic-grammar.ts"
        for type_list in ("<>", "< /*gap*/ >", "<T,>", "<T>"):
            yield filename, owner.replace("$", type_list), {"target": "esnext"}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler_archive", type=Path)
    cli.add_argument("source_archive", type=Path, nargs="?", help="Include original parameter and catch fixtures")
    args = cli.parse_args()
    archive = args.compiler_archive
    matrix = list(_MATRIX)
    matrix.extend(parameter_grammar_cases())
    matrix.extend(generic_grammar_cases())
    matrix.extend((filename, source, {"target": target})
                  for target in ("es5", "es2015", "esnext")
                  for filename, source in (
                      ("name.ts", "const café = 1;"), ("name.ts", "const 𐐀 = 1;"),
                      ("name.ts", r"const x\u{10400} = 1;"), ("name.ts", "f<𐐀>(v);"),
                      ("name.ts", "class C { #𐐀; }"), ("name.tsx", "<𐐀 />;"),
                      ("name.ts", "const x = /a/𐐀;")))
    matrix.extend(("names.ts", prefix + source, {}) for source in _STRICT_NAMES
                  for prefix in ("", 'export {};', '"use strict";'))
    if args.source_archive:
        check_pin(args.source_archive, SOURCE_SHA)
        fixtures = [
            ("conformance/es6/arrowFunction/disallowLineTerminatorBeforeArrow.ts", {}),
            ("conformance/functions/functionWithUseStrictAndSimpleParameterList.ts", {}),
            ("conformance/functions/functionWithUseStrictAndSimpleParameterList_es2016.ts", {"target": "es2016"}),
            ("compiler/catchClauseWithInitializer1.ts", {}),
            ("compiler/indexSignatureWithTrailingComma.ts", {}),
            ("compiler/optionalParameterInDestructuringWithInitializer.ts", {}),
            ("compiler/restParameterNotLast.ts", {}),
            ("compiler/classWithEmptyTypeParameter.ts", {}),
            ("compiler/emptyTypeArgumentList.ts", {}),
            ("compiler/emptyTypeArgumentListWithNew.ts", {}),
            ("conformance/types/objectTypeLiteral/callSignatures/callSignatureWithOptionalParameterAndInitializer.ts", {}),
            ("compiler/parameterInitializerBeforeDestructuringEmit.ts", {"alwaysStrict": True}),
            ("conformance/es6/destructuring/optionalBindingParameters1.ts", {}),
            ("conformance/es6/destructuring/optionalBindingParameters2.ts", {}),
            ("compiler/declarationEmitDestructuringWithOptionalBindingParameters.ts", {}),
        ]
        with tarfile.open(args.source_archive) as tar:
            for fixture, options in fixtures:
                source = tar.extractfile("TypeScript-5.9.3/tests/cases/" + fixture).read().decode("utf-8-sig")
                for name, unit in test_units(source, fixture):
                    matrix.append((name, unit, options))
    check_pin(archive, COMPILER_SHA)
    with tempfile.TemporaryDirectory() as directory:
        cases, actual = [], []
        for i, (filename, source, options) in enumerate(matrix):
            root = Path(directory) / str(i)
            root.mkdir()
            path = root / filename
            path.write_text(source)
            project = root / "tsconfig.json"
            project.write_text(json.dumps({"compilerOptions": options}))
            cases.append({"name": str(path), "options": options, "codes": _DIAGNOSTIC_CODES})
            result = get_pipeline(path, typescript_options=SyntaxOptions.from_project(project)).analyze_file(path)
            located, missing = [], []
            pending = [result.ast]
            while pending:
                node = pending.pop()
                if isinstance(node, dict):
                    located.extend((d["code"], d["offset"]) for d in node.get("diagnostics", [])
                                   if d.get("code") in _DIAGNOSTIC_CODES)
                    if "missingArgumentOffset" in node:
                        missing.append(node["missingArgumentOffset"])
                    pending.extend(node.values())
                elif isinstance(node, list):
                    pending.extend(node)
            actual.append((result.ast["sourceType"] if result.success else "reject", sorted(located), sorted(missing)))
        reference = run_compiler(archive, _ORACLE, cases)
    failures = 0
    for (filename, source, options), observed, row in zip(matrix, actual, reference, strict=True):
        # Target these syntax/strict-mode diagnostics; other isolated-program
        # diagnostics include missing symbols and JSX runtime dependencies.
        source_goal = "reject" if row["parse"] else ("module" if row["module"] else "script")
        expected = (source_goal, sorted(map(tuple, row["located"])), sorted(row["missing"]))
        if observed != expected:
            print(filename, options, repr(source), row, "Orion:", observed)
            failures += 1
    print(f"{len(actual)} option/file-kind checks, {failures} differences")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
