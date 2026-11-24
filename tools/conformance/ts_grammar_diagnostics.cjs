// Run the pinned grammar checker on one source file without resolving other files.
function isolatedDiagnostics(api, file, compilerOptions = {}) {
    const options = {...compilerOptions, target: file.languageVersion, noLib: true, noResolve: true, noEmit: true};
    const host = api.createCompilerHost(options);
    const absolute = name => api.getNormalizedAbsolutePath(name, "/");
    const isRoot = name => absolute(name) === absolute(file.fileName);
    host.getCurrentDirectory = () => "/";
    host.getSourceFile = name => isRoot(name) ? file : undefined;
    host.fileExists = isRoot;
    host.readFile = name => isRoot(name) ? file.text : undefined;
    return api.createProgram([file.fileName], options, host).getSemanticDiagnostics(file);
}

const parameterListCodes = new Set([1013, 1014, 1015, 1016, 1017, 1018, 1019, 1020, 1021, 1022, 1025, 1047, 1048, 1096]);

const genericListCodes = new Set([1009, 1097, 1098, 1099, 1172, 1173, 1174, 1175, 1176, 1326]);

function diagnosticPosition(file, d) {
    const start = Array.from(file.text.slice(0, d.start)).length;
    const position = [d.code, start];
    if (parameterListCodes.has(d.code) || genericListCodes.has(d.code) || d.code === 1200) {
        position.push(Array.from(file.text.slice(d.start, d.start + d.length)).length);
    }
    return position;
}

function diagnosticOrder(a, b) {
    return a[1] - b[1] || a[0] - b[0];
}

function functionGrammarDiagnostics(api, file) {
    return isolatedDiagnostics(api, file)
        .filter(d => parameterListCodes.has(d.code) || genericListCodes.has(d.code) || [1200, 1346, 1347, 7060].includes(d.code))
        .map(d => [...diagnosticPosition(file, d), (d.relatedInformation || []).map(r => diagnosticPosition(file, r))])
        .sort(diagnosticOrder);
}

function parameterGrammarDiagnostics(api, file) {
    const positions = new Set();
    const pending = [file];
    while (pending.length) {
        const n = pending.pop();
        // A final, plain optional or rest parameter alone cannot produce any
        // of the selected list diagnostics. Keep every non-final such parameter.
        if (api.isFunctionLike(n) && (api.isIndexSignatureDeclaration(n) || n.parameters.hasTrailingComma || n.parameters.some((p, i) =>
            (p.questionToken || p.dotDotDotToken) && (i + 1 < n.parameters.length || p.initializer ||
                (p.questionToken && p.dotDotDotToken))))) {
            if (api.isIndexSignatureDeclaration(n)) positions.add(n.getStart(file));
            if (n.parameters.hasTrailingComma) positions.add(n.parameters.end - 1);
            for (const p of n.parameters) {
                for (const token of [p.name, p.dotDotDotToken, p.questionToken]) {
                    if (token) positions.add(token.getStart(file));
                }
            }
        }
        api.forEachChild(n, child => { pending.push(child); });
    }
    if (!positions.size) return [];
    return isolatedDiagnostics(api, file)
        .filter(d => parameterListCodes.has(d.code) && positions.has(d.start))
        .map(d => diagnosticPosition(file, d)).sort(diagnosticOrder);
}


function genericGrammarDiagnostics(api, file) {
    const positions = new Set();
    const pending = [file];
    while (pending.length) {
        const n = pending.pop();
        if (api.isExpressionWithTypeArguments(n) && n.expression.kind === api.SyntaxKind.ImportKeyword) positions.add(n.getStart(file));
        if (n.typeParameters?.length === 0) positions.add(n.typeParameters.pos - 1);
        if (n.typeArguments?.length === 0) positions.add(n.typeArguments.pos - 1);
        if (n.typeArguments?.hasTrailingComma) positions.add(n.typeArguments.end - 1);
        if (n.heritageClauses) {
            const seen = new Set();
            for (const clause of n.heritageClauses) {
                if (seen.has(clause.token) ||
                    (clause.token === api.SyntaxKind.ExtendsKeyword && seen.has(api.SyntaxKind.ImplementsKeyword)) ||
                    (api.isInterfaceDeclaration(n) && clause.token === api.SyntaxKind.ImplementsKeyword)) {
                    positions.add(clause.getStart(file));
                }
                if (!clause.types.length) positions.add(clause.types.pos);
                if (clause.types.hasTrailingComma) positions.add(clause.types.end - 1);
                if (!api.isInterfaceDeclaration(n) && clause.token === api.SyntaxKind.ExtendsKeyword && clause.types.length > 1)
                    positions.add(clause.types[1].getStart(file));
                seen.add(clause.token);
            }
        }
        api.forEachChild(n, child => { pending.push(child); });
    }
    if (!positions.size) return [];
    return isolatedDiagnostics(api, file)
        .filter(d => genericListCodes.has(d.code) && positions.has(d.start))
        .map(d => diagnosticPosition(file, d)).sort(diagnosticOrder);
}


function importGrammarDiagnostics(api, file, options) {
    const positions = new Set(), pending = [file];
    while (pending.length) {
        const node = pending.pop();
        if (api.isImportCall(node)) {
            positions.add(node.getStart(file));
            if (node.arguments.hasTrailingComma) positions.add(node.arguments.end - 1);
            for (const arg of node.arguments) positions.add(api.getErrorSpanForNode(file, arg).start);
        }
        api.forEachChild(node, child => { pending.push(child); });
    }
    if (!positions.size) return [];
    return isolatedDiagnostics(api, file, options)
        .filter(d => [1009, 1286, 1295, 1323, 1324, 1325, 1326, 1450, 18060].includes(d.code) && positions.has(d.start))
        .map(d => [d.code, Array.from(file.text.slice(0, d.start)).length,
                         Array.from(file.text.slice(d.start, d.start + d.length)).length]).sort(diagnosticOrder);
}
