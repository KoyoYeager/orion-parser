// Print the TypeScript 5.9.3 reference parser/scanner and grammar-checker index.
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createRequire } from 'node:module';

const tag = 'v5.9.3';
const base = 'https://raw.githubusercontent.com/microsoft/TypeScript/' + tag + '/src/compiler/';
const files = {
    'parser.ts': 'dcddb577aa14f455193ca98c7c069217a0c523466fc777b985a7aefbd8dafc8e',
    'scanner.ts': '02f9e8f02e234b0e917e753a7b74f975c9b9b95f7f01ee4bc151081ed43dea49',
    'checker.ts': 'aba154f42352498790b55fa6995bdbb5dee607460eef5eebc1908b0cf0087d3c',
};

async function download(url, digest) {
    const response = await fetch(url);
    if (!response.ok) throw new Error('Download failed: ' + url);
    const data = Buffer.from(await response.arrayBuffer());
    if (createHash('sha256').update(data).digest('hex') !== digest) throw new Error('Unexpected digest: ' + url);
    return data;
}

function indexSource(ts, file, data) {
    const source = ts.createSourceFile(file, data.toString('utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
    if (source.parseDiagnostics.length) throw new Error('Reference could not parse ' + file);
    function location(node) {
        const {line, character} = source.getLineAndCharacterOfPosition(node.getStart(source));
        return (line + 1) + ':' + (character + 1);
    }
    function definition(node) {
        if (ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node)) return node.name?.getText(source);
        if (ts.isVariableDeclaration(node) && node.initializer &&
            (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))) {
            return node.name.getText(source);
        }
    }
    function walk(node, owner) {
        const name = definition(node);
        if (name) {
            const tracked = file !== 'checker.ts' || name.startsWith('checkGrammar') || owner;
            owner = tracked ? {name, start: location(node), choices: []} : undefined;
        }
        if (owner) {
            const where = location(node);
            if (ts.isCaseClause(node)) owner.choices.push(where + '=' + node.expression.getText(source).replace(/\s+/g, ' '));
            else if (ts.isDefaultClause(node)) owner.choices.push(where + '=default');
            else if (ts.isIfStatement(node) || ts.isConditionalExpression(node)) owner.choices.push(where + '=true/false');
        }
        ts.forEachChild(node, child => walk(child, owner));
        if (name && owner) console.log([file, name, owner.start, owner.choices.join('; ')].join('\t'));
    }
    walk(source, undefined);
}

const registry = 'https://registry.npmjs.org/typescript/-/typescript-5.9.3.tgz';
const archive = await download(registry, '10e108c9cf7d5f2879053dff18515fb405abf2ccef63eaaf017d9c571687a1d3');
const directory = mkdtempSync(join(tmpdir(), 'orion-ts-inventory-'));
try {
    const compiler = join(directory, 'typescript.cjs');
    writeFileSync(compiler, execFileSync('tar', ['-xzOf', '-', 'package/lib/typescript.js'], {
        input: archive, maxBuffer: 32 * 1024 * 1024,
    }));
    const ts = createRequire(import.meta.url)(compiler);
    if (ts.version !== '5.9.3') throw new Error('Unexpected TypeScript compiler version');
    console.log('source\tfunction\tline:column\tbranch locations');
    for (const [file, digest] of Object.entries(files)) indexSource(ts, file, await download(base + file, digest));
} finally {
    rmSync(directory, {recursive: true, force: true});
}
