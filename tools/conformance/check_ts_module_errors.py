"""Compare the first parse diagnostic and file goal during top-level await replay."""
import argparse
from collections import Counter
import tempfile
from pathlib import Path

from check_typescript import COMPILER_SHA, TypeScriptPipeline, _STATEMENT_SHAPE, check_pin, run_compiler
from check_ts_alias_shapes import project_trees
from orionparser.languages.javascript.pipeline import SourceSyntaxError
from orionparser.languages.typescript.options import SyntaxOptions


def cases():
    for marker in ("export {};", 'import "pkg";', 'import p=require("pkg");', "import.meta;",
                   "namespace N{export {};}", 'function f(){import("pkg");}', ""):
        for body in ("await; throw;", "await(v); throw;", "throw; await;", "await; throw; throw;", "await; x=;", "await; x+=; throw;", "x=; await;",
                     "await; throw /*𐐀*/ ;", "await; {throw;}", "await(v);"):
            for source in (marker + "\n" + body, body + "\n" + marker):
                yield "replay.ts", source, {}
    for name in ("replay.ts", "replay.mts", "replay.cts", "replay.tsx", "replay.d.ts", "replay.d.mts", "replay.d.cts"):
        for options in ({"moduleDetection": "force"}, {"moduleDetection": "legacy"}, {"moduleDetection": "auto"}):
            yield name, "await; throw;", options
    for name in ("ambient.ts", "ambient.tsx", "ambient.d.ts"):
        for declaration in ("declare function f():number;", "declare const x:T\n", "declare class C{}",
                            "declare interface I{}", "declare namespace N{declare const x:T; await(x);}"):
            for marker in ("", "export {}; "):
                yield name, marker + declaration + " await(x);", {}
    for decorator in ("import.meta.d", "import.defer?.<T>(x,)", "new.target.d", "super(x,)", "super.d",
                      "import('pkg')", "import<T>(x)", "import.defer<T>(x)", "(import.defer)?.(x,)"):
        yield "calls.ts", "@" + decorator + " class C {}", {}
        yield "calls.ts", "await; @" + decorator + " class C {}", {}
    for source in ("class C{@super [key](){}}", "function f(@super [a]:T){}",
                   "class C{constructor(@super [item]:T){}}", "class C{@super(x,)[key](){}}"):
        yield "decorated.ts", source, {}
    for option in ("preserve", "react-jsx"):
        for src in ("<C/>; await; throw;", "await; throw; <C/>;",
                    "await; const f=(...a(<C/>))=>v;", "await; const f=(...a(g(<></>)))=>v;",
                    'await; const f=(...a("<C/>"))=>v;'):
            yield "view.tsx", src, {"jsx": option}
        for expression in ("<A/><B/>", "<A/> /*gap*/ <B/> <C/>", "<A<T>></A><></>",
                           "<><A/></>\r\n<B>𐐀</B>", "<A/><B x={import.meta}/>", "f(<A/><B/>)",
                           "<A>{<B/><C/>}</A>", "<A/><B></C>", "<A/> < b", "<A/><B/>.x", "<A/><B/>()",
                           "<A/><B/>[i]", "<A/><B/>++", "<A/><B/>?.key", "+<A/> < limit",
                           "(<A/>) < limit", "<><A/><B/></>", "<A/><B/> => v", "<A/> => x",
                           "<A/>\r\n=> x", "f(<A/><B/> => import.meta)", "f(<A/> => x)",
                           "<A/><B/> => { export {}; }", '<A/><B/> => import("p")'):
            for source in (expression + ";", "await; " + expression + "; export {};"):
                yield "adjacent.tsx", source, {"jsx": option}
        for source in ("await <A/> < limit; export {};", "export {}; await <A/> < limit;",
                       "await <A/> < limit; import.meta;", "await; <C {x}/>; export {};",
                       "await; <C {import.meta}/>;", "await; <C ; prop/>; export {};",
                       "<C {} />;", "<C {...(x,y)}/>;", "<C a={x}/>;", "<C>{<B/>}</C>;",
                       "+<A/><B/>;", "await <A/><B/>; export {};", "export {}; await <A/><B/>;"):
            yield "adjacent.tsx", source, {"jsx": option}
    for source in ("<A/><", "<A/><B/>< /*gap*/", "<A/> /*gap*/ <>", "<A/><B/>\r\n<> text", "<A/> < b;", "<A/><B/> => v;"):
        yield "adjacent.tsx", source, {}
    for name in ("constructor.ts", "constructor.tsx", "constructor.d.ts", "constructor.mts"):
        for expression in ("new <A/>", "new <T>()", "new <<T>()=>T>()", "new > x",
                           "new <= x", "new", "f(new, x)", "[new]", "new C<A>()",
                           "obj.new<A>()", "new /x/", "new (C)()", "new C?.p", "new C<T>?.()",
                           "new C?.[import.meta]", 'new C?.[import("p")]', "new new C()?.p",
                           "new (C?.p)()", "new C()?.p", "new C()?.[#x]", "new C<T>.p",
                           "a<A<B>>.p", "a<T, /*gap*/>.p", "a?.b<T>.#k", r"a<T>?.#\u0078",
                           "a<T>.#𐐀", "a?.x[#k]", "a?.[#p]", "(a<T>).b"):
            for source in (expression + ";", "await; " + expression + "; export {};"):
                yield name, source, {}
        for source in ("new", "new /*gap*/", "function f(){new", "new\r\n", "type C = new <T>() => T;", "declare const C: new<T>()=>T; new C<A>();",
                       "interface I{new<T>():T}", "class C{new<T>(){}}", "@a?.[#k] class K{}",
                       "@new C<T>?.d class K{}", "@a<T>.p class K{}", "@a<T>?.#k class K{}"):
            yield name, source, {}
    for name in ("super.ts", "super.tsx", "super.d.ts"):
        for expression in ("super<T>(x,)", "super /*gap*/ <T> (x)", "super<>()", "super<T>`x`",
                           "super < x", "super<T>=>x", "super <<T>()=>T>()", "super?.(x)", "super?.[import.meta]",
                           "super!", "super property", "super.x<T>(x,)", "new super<T>(x,)", "obj.super<T>()"):
            for src in (expression + ";", "await; " + expression + "; export {};"):
                yield name, src, {}
        for src in ("super", "super /*gap*/", "({super<T>(x:T){}});", "@super(x,) class C{}"):
            yield name, src, {}
    for source in ("a<b>=c;", "a<b>>>c;", "a<b>===c;", "f<T> >=v;", "f<T>\n>>v;",
                   "a / >= c;", "a >= == b;", "await; a >= > c; export {};"):
        yield "operator.ts", source, {}
    for expression in ("a<b>>=c", "a<b>>>=c", "a+b=c", "f(a+b=c)", "[a+b=c]", "(a+b=c)",
                       "a?b+c=d:e", "a+b\n=c", "f(a+b\n=c)", "let x=a+b>>=c",
                       "a>>=c", "a>>>=c", "let x:A<B>=v"):
        for src in (expression + ";", "await; " + expression + "; export {};"):
            yield "assignment.ts", src, {}
    for control in ("if", "while", "with"):
        for suffix in ("v) {}", "import.meta) {}", 'import("p")) {}', "v; export {}) {}",
                       "v; { export {}; }) {}", "fn(g(x)); export {}) {}"):
            yield "control.ts", "await; " + control + "(x+y = " + suffix, {}
    for prefix, closing in (("if(f(", ")) {}"), ("if((", ")) {}"), ("while(f(g(", "))) {}"),
                            ("switch(", "){default:break;}")):
        for rhs in ("v; export {}", "import.meta", 'import("pkg")', "v; {export {};}", "v; function f(){return import.meta;}"):
            yield "nested.ts", "await; " + prefix + "x+y = " + rhs + closing + ";", {}
    for expression in ("<A>{x+y = import.meta}</A>", "<A a={x+y = import.meta}/>",
                       '<A>{x+y = "export {};"}</A>', 'f(x+y = import("p"))', "f(x+y = import.meta)"):
        for ending in (";", "; export {};"):
            yield "assignment.tsx", "await; " + expression + ending, {}
    for src in ("throw;", "throw; throw;", "export {}; await", "export {}; await   ", 'throw\nvalue;',
                "export {}; await; value=;", "export {}; await v; throw; await(x);"):
        yield "replay.ts", src, {}
    for name in ("a.ts", "a.d.ts", "a.d.cts", "a.tsx"):
        for source in ("export {}; await;", "export {}; await(x);", "export {}; await; throw;",
                       "await; x=; export {};", "export {}; class C{[await+v](){}} await; throw;",
                       "export {}; namespace N{const x=await;} await; throw;"):
            yield name, source, {}
    for incomplete in ("const = 1;", "const default=0;", "var if=1;", "const 42;", 'var "x"=1;',
                       "const\n=1;", "var a,/*𐐀\n*/:T=1;", "for(const\n=1;;){}", "switch(x){case 0:var\n,;}", "const :T=1;", "var ,;", "let a,,b;", "var = v;", "let x, = v;", "for (const =1;;){}",
                       "@d using =v;", "@d using if=1;", "@d using\n=v;",
                       "for (var a, = v;;){}", "{const /*𐐀*/ = 1;}", "f(,);", "new F(x,,y);",
                       "function f(,){}", "function f(x,,y){}", "function f(in){}", "function f(1){}", "function f(if){}",
                       "({#x});", "({42});", "({'x' /*𐐀*/ ,y:2});", "({[key] = rhs});",
                       "({default});", "({nested:{[key]}});", "({x:});", "({[key]:});", "({x: /*𐐀*/ ,y:2});", "({x:{y:}});",
                       "({x:v + });", "[v * ];", "f(x = );", "f(x + ,y);", "let x:;",
                       "function f(x:){}", "type T=[x:];", "type T={[k:string]:};", "let x: =v;",
                       "const {x:}=v;", "function f({x: ,y}){}", "type T={x:};",
                       "type T={x: ,y:K};", "type T={x: ;};", "({,x:1});", "({:x});", "x + ;", "const y = !;", "let x=1, y=;", "throw ;", "x = ;", "class C{m(){x * ;}}"):
        for source in ("await; " + incomplete + " export {};", incomplete + " await; export {};",
                       "await; " + incomplete):
            yield "replay.ts", source, {}
    for expr in ("await /x/;", "await /x/.test(y);", "await /(?:x)/;", "await /x/?.test(y);"):
        for source in (expr + " namespace N{} throw;", "throw; " + expr + " namespace N{}",
                       expr + " namespace N{} throw; export {};", expr + " namespace N{} throw )", "export {}; " + expr + " namespace N{} throw;"):
            yield "regexp.ts", source, {}
    for clause in ('import x, from "p";', 'import type X, from "p";', 'import x, 1;', 'import x,'):
        for source in (clause, "await; " + clause, "function f(){" + clause + "} await;"):
            yield "imports.ts", source, {}
    for head in ("const", "var", "let a,", "const a,"):
        for gap in (" ", "\n", "/*𐐀\r\n*/"):
            for tail in ("42;", '"abc";', "[x]=v;", "{x}=v;", "x=1;", "=1;", ":T=v;", ",;"):
                yield "binding.ts", head + gap + tail, {}
    for name in ("props.ts", "props.tsx", "props.d.ts"):
        for marker in ("", "export {}; "):
            for source in ("const value={x:1}; const {x:y}=value;", "type T={x:number; y?:string};",
                           "const value={outer:{[key]:left+right},...more};", "const value={let, [key]:x, 42:y};"):
                yield name, marker + source, {}

    for source in ("export {}; ({await}, {async f(x=await){}});", "export {}; ({await}, {m(){return await;}});",
                   "export {}; {({await}); try{}catch(await){}}", "export {}; {({await}); try{}catch({await}){}}",
                   "export {}; {({await}); enum X{v=await}}", "export {}; ({await}, o.await);", "export {}; ({await}, await);",
                   r"export {}; ({\u0061wait});", "export {}; ({await=1});", "export {}; ({await=await});"):
        yield "replay.ts", source, {}

    for name in ("keywords.ts", "keywords.tsx", "keywords.mts", "keywords.cts",
                 "keywords.d.ts", "keywords.d.mts", "keywords.d.cts"):
        for key in ("await", "yield"):
            obj = "({" + key + "});"
            for statement in (obj, "if (c) " + obj, "function f(){" + obj + "}",
                              "async function f(){" + obj + "}", "function* f(){" + obj + "}",
                              "async function* f(){" + obj + "}", "await " + obj,
                              "f({" + key + "}, await x);"):
                for src in ("export {}; " + statement, statement + " export {};"):
                    yield name, src, {}

    for src in ("export default interface {}", "export default interface<T>{}", "export default interface extends X{}",
                "export default interface await{}", "export default interface  ", "declare type\n", "declare type /*x*/",
                "export default @d type X=T;", "export default @d declare type await<T>=T;",
                "export default @d async type X=T;", "export default @d type\nX=T;",
                "async function* f(){export default @d type yield=T;}", "@d interface\nX{}",
                "export default interface enum{}"):
        yield "defaults.ts", src, {}
    for name in ("recovery.ts", "recovery.tsx"):
        for head in ("type await", "interface yield"):
            for operand in ("<T/>;", "<T></T>;", "<T>=T;", "(x);"):
                body = "async function* f(){" + head + operand + "}"
                for src in ("await; " + body + " export {};", body, "export {}; await; " + body):
                    yield name, src, {}
    for src in ("<A>{x</A>;", "<A>{x+</A>;", "<A>{f(x</A>;", "<A>{f(</A>;", "<A>{(x</A>;",
                "<A v={x</A>;", "x</r/.test(y);", "<A>{x < /r/.test(y)}</A>;",
                "await; <A>{x</A>; export {};", "await; <A>{f(</A>; export {};",
                "await; <A>{(x</A>; export {};", "await; <A>{x?y</A>; export {};",
                "await; <A>{</A>; export {};", "await; <A>{x in =y}</A>; export {};",
                "await; <A>text}</A>; export {};", "x\n</A>", "await; x</r/; export {};",
                "await; x</r/.test(y); export {};", "await; x.y</A>; export {};", "await; x\n</A>; export {};",
                "await; </A>; export {};", "await; <A><B>{x</A>; export {};", "<A><B></A>;",
                "await; <UI.A<T>><B><C/></UI.A>; export {};", "await; <X></Y>; export {};",
                "await; <A><B><C></A>; export {};", "await; <A><B></Q>; export {};"):
        yield "closing.tsx", src, {}
    for source in ("<T/x/;", "</x/;", "<T/abc>", "<T /abc/; export {};", "<T>=x;", "<T>/x/;"):
        yield "assert.ts", source, {}
    for name in ("regexp.ts", "regexp.tsx"):
        for tail in ("", "a", "abc)tail", "𐐀]tail", "[[a]](b){2}}", r"a\)b}",
                     "a;(b);  ", "a\u0085;\u200b", "[[]", "(a\nnext", "a\\\r\nnext"):
            yield name, "/" + tail, {}
        for src in ("await; /x); export {};", "await; const x=/r]; export {};", "const x=/r];",
                    "function f(){return /x)} await; export {};", "f(/x);"):
            yield name, src, {}
        for op in ("in", "instanceof", "+", "**"):
            for src in ("x " + op + " = y;", "await; x " + op + " = y; export {};",
                        "f(x " + op + " = y);", "[x " + op + " = y];"):
                yield name, src, {}

    for name in ("params.ts", "params.tsx"):
        for bad in ("1", "'x'", "T,1", ",", "T,,U", "const 1", "const if", "T 1"):
            for src in ("({m<" + bad + ">(){}});", "function f<" + bad + ">(){}",
                        "type F<" + bad + ">=T;", "class C<" + bad + ">{}"):
                yield name, src, {}
        for src in ("await; ({x<1>(){}}); export {};", "await; function f<T,1>(){} export {};",
                    "({x<T,  ", "({x<", "({x<(){} });", "({x<T extends 1>(){}});"):
            yield name, src, {}
    for src in ("({x</A>});", "await; ({x</A>}); export {};", "({x<A>,y});",
                "await; class C{x<T>} export {};", "await; ({x<A>}); export {};"):
        yield "params.ts", src, {}
    for name in ("power.ts", "power.tsx"):
        for expr in ("+x", "- -x", "typeof obj.x", "!f(x)", "void (x)", "delete obj[k]",
                     "~𐐀", "- /*c*/ (a)", "await f(x)", "++x", "x++", "(-x)"):
            for source in (expr + " /*gap*/ ** b;", "async function f(){return " + expr + " ** b;}",
                           "x + " + expr + " ** y ** z;", "await; " + expr + " ** b; export {};"):
                yield name, source, {"target": "es2015"}
        for target in ("es5", "es2015"):
            yield name, "~𐐀 ** b;", {"target": target}
    for source in ("\ufffd", "x;\ufffd", "x;#!", "x;\0", "♞;"):
        yield "scanner.ts", source, {}
    for name in ("unicode.ts", "unicode.tsx"):
        for target in ("es5", "es2015"):
            for fragment in ("~𐐀 ** b;", "f(𐐀);", "let 𐐀=1;", "𐐀;", "x;\x01", "f(♞);"):
                for src in (fragment, "await; " + fragment + " export {};", "await; " + fragment):
                    yield name, src, {"target": target}
            for src in ("await; 𐐀import.meta;", "await; 𐐀 export {};", "await; � export {};",
                        "await; '♞'; export {};", "await; /♞/.test(x); export {};"):
                yield name, src, {"target": target}
    for target in ("es5", "es2015"):
        for escape in (r"\u0030", r"\u002d", r"\uG123", r"\u{}", r"\u{110000}", r"\u{61",
                       r"\u{30", r"\u{10400}", r"\u{10400", r"\u0061", r"\x61"):
            for source in (escape + ";", "a" + escape + ";", "obj.#" + escape + ";",
                           "await; a" + escape + "; export {};"):
                yield "escape.ts", source, {"target": target}
        for source in (r"a\u{61", r"a\u{30", r"\u{30", r"obj.#\u{61", "obj.#", "obj.#1"):
            yield "escape.ts", source, {"target": target}
        for tail in (r"\u{61z", r"\u{30z", r"\u{61\u0061", r"\u{10400z"):
            for head in ("", "a", r"a\u0062"):
                yield "escape.ts", "await; " + head + tail + "; export {};", {"target": target}
        for tag in (r"A\u0062", r"a-\u{61", r"\u0030", "♞"):
            for expression in ("<" + tag + "/>", "+<" + tag + "/>", "<R " + tag + "/>"):
                yield "escape.tsx", "await; " + expression + "; export {};", {"target": target}
        for tag in (r"\u0030", r"a\u0062-z", r"Z-\u{30", "𐐀-a", "♞", "a-♞", "�"):
            for expr in ("<X." + tag + "/>", "<X></" + tag + ">", "<R><" + tag + "/></R>"):
                yield "nested.tsx", "await; " + expr + "; export {};", {"target": target}
    for name in ("numbers.ts", "numbers.tsx"):
        for literal in ("1", ".125", "1.0", "2e3", "1n"):
            for suffix in ("word", "𐐀name", r"foo\u0061", r"x\u{61}", "n", "next"):
                yield name, literal + suffix + ";", {"target": "es2015"}
        for literal in ("0b1", "0o7", "0xff", "0b1n"):
            for operator in ("in obj", "instanceof C", "satisfies T"):
                yield name, literal + operator + ";", {}
        for literal in ("2e+", "1E", "3e-"):
            yield name, literal + ";", {}
        for literal in ("1__2", "1___2", "1_", "1._2", "1.2__3", "1e+_2", "1E2__3", "0_9",
                        "0x_1", "0x1__F", "0o7_", "0b1_2", "0b_0", "0x", "0o", "0b", "0b2",
                        "12_3.4_5E-6_7", "0xA_Bn", "0O6_7", "0B1_0n", "0n_a"):
            for source in (literal + ";", "await; " + literal + "; export {};"):
                yield name, source, {}
        for literal in ("01", "077", "01x", "08", "09foo", "08.1e3", "08.1__2", "08e+", "08_2"):
            for prefix in ("", "-", "x- /*𐐀*/ "):
                yield name, prefix + literal + ";", {}
            yield name, "await; " + literal + "; export {};", {}
        for pair in ("0xFFg", "0b102", "0o78", "1n2", "0x1nfoo", "0b1.2"):
            for source in (pair + ";", "let a=" + pair + ";", "f(" + pair + ");", "(" + pair + ");",
                           "[" + pair + "];", "await; " + pair + "; export {};"):
                yield name, source, {}
        for source in ("0xFF\ng;", "f(0xFF\ng);", "for(0b1of obj){}", r"for(1\u006ff arr){}",
                       r"1\u0061s T;", r"1\u0069n obj;", "type T=0xFFg;"):
            yield name, source, {}
        for receiver in ("0b1", "0o7n", "0xFF", "x", "obj[k]"):
            for tail in (".;", ". /*gap*/", ".\r\n;", ".>>;", "?.;", "?.  "):
                yield name, receiver + tail, {}
            yield name, "await; " + receiver + ".; export {};", {}
        for incomplete in ("0x", "0b", "0o"):
            yield name, incomplete, {}
        yield name, "await; 1foo; export {};", {}
    for name in ("keys.ts", "keys.tsx"):
        for prefix in ("0xFF", "0b1", "'get'", "[get]", "name", "default", "async\n"):
            for suffix in ("g:v", "g(){}", "g<T>(){}"):
                obj = "({" + prefix + " " + suffix + "});"
                yield name, obj, {}
                yield name, "await; " + obj + " export {};", {}
        for source in ("({get x(){return n},set x(v){}});", "({get\n[key](){return x}});",
                       "({get<T>(v:T){return v}});", r"({g\u0065t x(){}});",
                       r"({s\u0065t x(v){}});", "({0xFFg:v});"):
            yield name, source, {}
    for key in ("get", "set", "static", "out", "const", "in", "public"):
        for src in (f"type F<#{key} T>=T;", f"type F<const #{key}>=T;", f"type F<#{key}>=T;",
                    f"({{#{key} next(){{}}}});", f"class C{{#{key} next(){{}}}}"):
            yield "private-keys.ts", src, {}
    for src in ("export default #interface X{}", "for #await(v of xs){}",
                'import x from "p" #with {type:"json"};', 'import x from "p" #assert {type:"json"};',
                "class C{#static {}}", "({#get(){}, #set(){}});", "({get #get(){return x}});",
                "class C{get #set(){return x} #get(){}}"):
        yield "private-keys.ts", src, {}
    for name in ("arrow.ts", "arrow.tsx", "arrow.mts", "arrow.d.cts"):
        for prefix in ("", "async "):
            for head in ("(...#x)", "(...#x:T[])", "(x:T,#y)", "(x?,#y)", "(public x,#y)", "(...xs)",
                         "(x:T)", "(x?:T)", "({#x:y})", "(x,y)", "(x = f())"):
                source = "const f=" + prefix + head + "=>x;"
                for src in (source, "await; " + source + " export {};"):
                    yield name, src, {}
        for expression in ("(#x)=>x", "async(#x)=>x", "(#x:T)=>x", "(x,#y)=>x", "(#x=0)=>x",
                           "([#x])=>x", "({x:#y})=>x", "(#x):T=>x", "((#x))=>x", "(x,...#y)=>x",
                           "(#x,)=>x", "(#x?)=>x", "(#x?:T)=>x", "(#x,y:T)=>x", "flag?(#a):b=>b", "f(#a)", "(#a)", "f((#x)=>y)"):
            for src in (expression + ";", "await; " + expression + "; export {};"):
                yield name, src, {}
        for head in ("x+y", "f()", "a.b", "obj[k]", "1", "x+=y", "(x)", "x?y:z", "x as T", "x,y()"):
            for src in ("const f=(" + head + ")=>x;", "async(" + head + ")=>y;", "flag?(" + head + "):z=>z;",
                        "switch(x){case (" + head + "):z=>z;}", "await; (" + head + ")=>; export {};"):
                yield name, src, {}
        for src in ("f()=>x;", "f(x)=>x;", "f(...x)=>x;", "(async)(x)=>x;", "obj?.(x)=>x;",
                    "new C(a)=>x;", "x?f(x):a=>a;", "switch(x){case f(x):a=>b;}",
                    "await; f(x)=>x; export {};", "f()\n=>x;"):
            yield name, src, {}
        for src in ("();", "(x,);", "(x,...y);", "async(x,);", "f((x,));", "((#x,));", "await; (x,...y); export {};",
                    "(x+y,)=>x;", "flag?(x+y,):z=>z;", "flag?(x+y,...y):z=>z;",
                    "f((x+y)=>y);", "((x+y)=>y);", "(x+y)\n=>x;", "(x+y):T=>x;"):
            yield name, src, {}
        for item in ("a.b", "a?.b", "a[b]", "a()"):
            for source in ("const f=(..." + item + ")=>v;", "const f=(x,..." + item + ")=>v;",
                           "const f=(" + item + ")=>v;", "function f(" + item + "){}",
                           "function f([" + item + "]){}", "f(..." + item + ");"):
                yield name, source, {}
        for src in ("await; function f(...a.b){} export {};", "function f(x:a[b]){}",
                    "const f=(x:a.b)=>v;", "const a\n[b]=v;"):
            yield name, src, {}
        for args in ("", "g(x)", "...xs", "x,y,", "import.meta", 'import("p")', '"export {};"'):
            binding = "const f=(...a(" + args + "))=>v;"
            for src in (binding, "await; " + binding, "await; " + binding + " export {};"):
                yield name, src, {}
        for src in ("!x;", "let x!:T;", "class C{x!:T}", "x!.y;", "function f(x!){}", "function f(...x! :T){}"):
            yield name, src, {}
        for suffix in ("()()", "().b", "()[k]", "(x).b(y)", "(x)?.y", "()[import.meta]",
                       "()?.(import.meta)", '()(<T>(x:T)=>x)', '()(`export {};`)', "().b<T>(x)", "!", "!(x)", "!?.(import.meta)", "?.(import.meta)", "?.(x).b",
                       "[x+y]", "[x-y]", "[import.meta]", "?.[import.meta]", ".import.meta",
                       "[x=import.meta]", "[x+import.meta]", "[g(import.meta)]", '[g(import("p"))]'):
            binding = "const f=(...a" + suffix + ")=>v;"
            for src in ("await; " + binding, "await; " + binding + " export {};",
                        "f(...a" + suffix + ");"):
                yield name, src, {}
        for element in ("import.meta", "0", "false", "if", 'x,"y"', "...default", "...1"):
            declaration = "function f([" + element + "]){}"
            for src in (declaration, "await; " + declaration + " export {};"):
                yield name, src, {}
        for modifier in ("private", "readonly", "override"):
            for expression in (f"({modifier} as number)", f"({modifier} satisfies T)", f"(({modifier}) satisfies T)",
                               f"({modifier} as:T)=>0", f"({modifier} satisfies:T)=>0", f"(x,{modifier} as:T)=>0"):
                yield name, "const result=" + expression + ";", {}
        for src in ("(...x);", "async(...x);", "(x:T){}", "await; async(...x); export {};",
                    "(...x) /*gap*/", "async(...#x);", "async(x,y);", "f(...#x);", "new async(...x);"):
            yield name, src, {}
    for name in ("param.ts", "param.tsx", "param.d.ts"):
        for binding in ("#x", "x,#if", "...#x", "private #x:T", "@d #x", "{#x:y}", "{x:#y}", "[#x]",
                        "{#x}", "{...#x}", "{#x=1}", "{default}", "{#x:#y}", "{x=o.#x}"):
            for src in ("function f(" + binding + "){}", "await; function f(" + binding + "){} export {};"):
                yield name, src, {}
        for src in (r"function f(#\u0078){}", "function f(#𐐀){}", "function f(\r\n  #x){}",
                    "await; ({m(...#x){}}); export {};"):
            yield name, src, {"target": "es2015"}
        for src in ("class C{constructor(private #x:T){}}", "({set p(#x){}});", "const #x=1;",
                    "var #x;", "let #x=1;", "let\n#x;", "for(let #x=1;;){}", "try{}catch(#x){}",
                    "const {#x:y}=o;", "let a=1,#x=2;"):
            yield name, src, {}
    for tag in ("ns:A.B", "ns:A:Q", "A..B", "ns:A.1", "A.", "ns:A", "UI.Icon"):
        for body in (f"<{tag}/>;", f"<Root></{tag}>;"):
            for src in (body, "await; " + body + " export {};", "export {}; " + body):
                yield "namespaced.tsx", src, {}
    for name in ("update.ts", "update.tsx", "update.d.ts"):
        for key in ("await", "yield"):
            for body in ("++" + key + "(x);", "--" + key + ";", "++(" + key + "(x)) ** y;"):
                for src in (body, "export {}; " + body, "async function f(){" + body + "}",
                            "function* f(){" + body + "}", "async function* f(){" + body + "}"):
                    yield name, src, {}
        for expr in ("++-x;", "++++x;", "++typeof x;", "++<T>x;", "--(x+y);", "++x++;", "x++++;", "f(++x++);", "(++x++);",
                     "[x++++];", "x as T++;", "++x\n++y;", "await; ++x++; export {};"):
            yield name, expr, {}
    for expr in ("<T>x", "<T>-x", "!<T>x", "(<T>x)", "- //note\n𐐀", "x as T + -a"):
        yield "assert.ts", expr + " ** y;", {"target": "es2015"}
    yield "constraint.ts", "type F<T extends +a ** b>=T;", {}
    for name in ("constraint.ts", "constraint.tsx"):
        for separator in (" extends", " =", " extends U ="):
            for trivia in ("", "   ", " /*𐐀*/", "\r\n"):
                yield name, "type F<T" + separator + trivia, {}
                yield name, "type F<T" + separator + " U" + trivia, {}
            for tail in (">=T;", " >=T;", ",U>=T;"):
                decl = "type F<T" + separator + tail
                for src in (decl, "await; " + decl + " export {};"):
                    yield name, src, {}
        for expression in ("/x/ ** n", "class {} ** n", "--x ** n", "(/x/ ** n)", "/x/"):
            for rest in (">=T;", "> =T;", " = U>=T;", ",U>=T;"):
                yield name, "type F<T extends " + expression + rest, {}
        for src in ("await; type F<T extends /x/ ** b>=T; export {};", "({x<T extends>(){}});", "function f<T, const U extends ,V>(){}",
                    "type F<T extends 1 = 2>=T;", "type F<T extends U = V>=T;"):
            yield name, src, {}
    for header in ("({m<@>(){}});", "async function f<@>(){}", "function* f<@>(){}", "type F<@>=T;"):
        for prefix in ("", "const ", "out ", "in ", "static ", "readonly "):
            for name in ("T", "in", "out", "const", "await", "yield", "implements", "if", "1"):
                yield "params.ts", header.replace("@", prefix + name), {}
    for malformed in ("export type as=T;", "export type =T;", "export type default=T;",
                      "export type @d X;", "export type\ndefault=T;"):
        for src in (malformed, "await; " + malformed, "await; function f(){" + malformed + "}"):
            yield "exports.ts", src, {}
    for declaration in ("type as=T;", "declare type as=T;", "export declare type as=T;"):
        yield "exports.ts", declaration, {}

    for name in ("decl.ts", "decl.tsx", "decl.mts", "decl.cts", "decl.d.ts", "decl.d.mts", "decl.d.cts"):
        for key in ("await", "yield"):
            for declaration in (f"type {key}<T>=T;", f"interface {key}{{p:T}}"):
                for src in (declaration, "export {}; " + declaration, "export " + declaration,
                            "export {}; declare " + declaration, "export {}; {" + declaration + " await(v);}",
                            "function f(){" + declaration + "}", "async function f(){" + declaration + "}",
                            "function* f(){" + declaration + "}", "async function* f(){declare " + declaration + "}",
                            "async function* f(){export " + declaration + "}",
                            "await; async function* f(){" + declaration + "} export {};",
                            "await; async function* f(){declare " + declaration + "} export {};"):
                    yield name, src, {}


def check_file_formats(archive):
    oracle = """
    const ts = require(process.argv[1]);
    const cases = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
    process.stdout.write(JSON.stringify(cases.map(({name, options}) => {
        const config = ts.convertCompilerOptionsFromJson(options, ".").options;
        const program = ts.createProgram([name], {...config, noLib:true, noEmit:true, types:[], allowNonTsExtensions:true});
        const file = program.getSourceFile(name);
        const last = file.statements.at(-1).expression;
        const diagnostics = program.getSemanticDiagnostics(file).filter(d => d.code === 7060 || d.code === 7059);
        return {syntax: [ts.ScriptKind[file.scriptKind], file.isDeclarationFile, ts.isExternalModule(file),
            ts.SyntaxKind[last.kind], diagnostics.map(d => d.code).sort()],
            optionCodes: program.getOptionsDiagnostics().map(d => d.code)};
    })));
    """
    failures = 0
    option_errors = Counter()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "package.json").write_text('{"type":"module"}')
        cases = []
        for directory, manifest in (("src", None), ("src/nested", "commonjs"), ("node_modules/own", "module"),
                                    ("node_modules/unscoped", None)):
            folder = root / directory
            folder.mkdir(parents=True)
            if manifest is not None:
                (folder / "package.json").write_text('{"type":"' + manifest + '"}')
            for name in ("file.ts", "file.TS", "file.TsX", "file.d.ts", "file.D.ts", "file.d.css.ts",
                         "file.mts", "file.MTS", "file.d.mts", "file.D.mts", "file.cts", "file.CTS"):
                path = folder / name
                source = "const f=<T>(x:T)=>x; const n=<number>1; await(f);"
                if path.suffix.lower() == ".tsx":
                    source = "const f=<C/>; await(f);"
                path.write_text(source, encoding="utf-8")
                for options in ({}, {"module":"nodenext"}, {"module":"nodenext", "moduleResolution":"node16"},
                                {"module":"nodenext", "moduleResolution":"bundler"},
                                {"module":"commonjs", "moduleResolution":"node16"}, {"jsx":"react-jsx"},
                                {"module":"node16", "moduleResolution":"node16"},
                                {"module":"esnext", "moduleResolution":"bundler"}):
                    cases.append({"name": str(path), "options": {"moduleDetection":"auto", **options}})
        for case, expected in zip(cases, run_compiler(archive, oracle, cases), strict=True):
            path = Path(case["name"])
            parser = TypeScriptPipeline(path)
            parser.syntax_options = SyntaxOptions.from_compiler_options(case["options"])
            tree = parser.parse(path.read_text(encoding="utf-8"))
            codes = []
            for statement in tree["body"][:-1]:
                initializer = statement["declarations"][0]["init"]
                codes.extend(d["code"] for d in initializer.get("diagnostics", []) if d["code"] in (7059, 7060))
            actual = [tree["scriptKind"], tree["declarationFile"], tree["sourceType"] == "module",
                      tree["body"][-1]["expression"]["type"], sorted(codes)]
            if expected["optionCodes"]:
                option_errors[tuple(sorted(expected["optionCodes"]))] += 1
            if actual != expected["syntax"]:
                print(path.relative_to(root), case["options"], actual, expected["syntax"])
                failures += 1
    print(f"{len(cases)} package/file-name comparisons, {failures} syntax differences, reference option diagnostics {dict(option_errors)}")
    return failures


def check_import_calls(archive, oracle):
    cases = []
    modules = ("none", "commonjs", "amd", "system", "umd", "es6", "es2015", "es2020", "es2022",
               "esnext", "node16", "node18", "node20", "nodenext", "preserve")
    for module in modules:
        for phase in ("import", "import.defer"):
            for suffix in ("()", '("p")', '("p",)', '<>("p")', '<T>("p", o,)', '("p", o)',
                           '("p", o,)', '("p", x, y)', "(...xs)", '("p", ...ys)'):
                cases.append(("call.ts", phase + suffix + ";", {"module": module, "target": "esnext"}))
    for filename in ("call.ts", "call.cts", "call.mts", "call.d.cts", "call.tsx"):
        for options in ({"module": "commonjs", "verbatimModuleSyntax": True},
                        {"module": "esnext", "verbatimModuleSyntax": True}, {"target": "es5"}, {"target": "esnext"}):
            for expr in ('import("p")', 'import.defer?.<T>("p",)', '(import.defer)?.("p",)'):
                cases.append((filename, expr + ";", options))
    for argument in ('((opts))', 'x satisfies T', 'o[fn(x,)]', '... /*𐐀*/ args',
                     'async function* named(){}', 'function (){}', 'class K {}', 'class {}',
                     '(x:T) /*gap*/ =>{\r\nreturn x}', '()=> /*gap*/\n{return 1}', 'x ** y',
                     'tag`x${v}`', '/[)]/u', 'v as Box<T>', 'f<A<B>>(v)', '<C/>'):
        for ending in (")", ",)"):
            cases.append(("span.tsx", 'import("p", /*𐐀*/ ' + argument + " /*end*/" + ending + ";", {"module": "commonjs"}))
    inputs = [dict(name=n, source=s, options=o, projection="import grammar", compilerModuleDetection=True)
              for n, s, o in cases]
    oracle = Path(__file__).with_name("ts_grammar_diagnostics.cjs").read_text() + oracle
    failures = 0
    for case, ref in zip(inputs, run_compiler(archive, oracle, inputs), strict=True):
        parser = TypeScriptPipeline(case["name"])
        parser.syntax_options = SyntaxOptions.from_compiler_options(case["options"])
        actual = project_trees(parser.parse(case["source"]), case["projection"])
        if actual != ref.get("trees"):
            print(case["name"], repr(case["source"]), case["options"], actual, ref)
            failures += 1
    print(f"{len(cases)} dynamic import comparisons, {failures} differences")
    return failures


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("compiler", type=Path)
    archive = cli.parse_args().compiler
    check_pin(archive, COMPILER_SHA)
    inputs = [dict(name=n, source=s, options=o, projection="file context", diagnosticSpans=True,
                   compilerModuleDetection=True) for n, s, o in cases()]
    oracle = _STATEMENT_SHAPE + Path(__file__).with_name("ts_alias_oracle.cjs").read_text()
    refs = run_compiler(archive, oracle, inputs)
    accepted = exact = failures = 0
    for case, ref in zip(inputs, refs, strict=True):
        parser = TypeScriptPipeline(case["name"])
        parser.syntax_options = SyntaxOptions.from_compiler_options(case["options"])
        try:
            tree = parser.parse(case["source"])
        except SourceSyntaxError as error:
            actual = [error.code, error.offset, error.length]
            if ref.get("diagnostics", [])[:1] == [actual]:
                line, column = ref["cliLocation"]
                if str(error).startswith(f"line {line}, column {column}:"):
                    exact += 1
                    continue
                actual = [actual, str(error)]
        else:
            actual = project_trees(tree, case["projection"])
            if actual == ref.get("trees"):
                accepted += 1
                continue
        print(case["name"], repr(case["source"]), case["options"], actual, ref)
        failures += 1
    print(f"{accepted} matching file trees, {exact} exact first diagnostics, {failures} differences")
    return int(bool(failures + check_file_formats(archive) + check_import_calls(archive, oracle)))


if __name__ == "__main__":
    raise SystemExit(main())
