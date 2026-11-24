// Instrument a temporary copy of the pinned compiler, leaving the AST oracle pristine.
const fs = require("node:fs");
const Module = require("node:module");
const compiler = process.argv[1];
const ts = require(compiler);
const {cases, sites, sources} = JSON.parse(fs.readFileSync(0, "utf8"));
const code = fs.readFileSync(compiler, "utf8");
const bundle = ts.createSourceFile(compiler, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
const originals = new Map(Object.entries(sources).map(([name, source]) =>
    [name, ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true)]));

function descendants(node, visit) {
    visit(node);
    ts.forEachChild(node, child => descendants(child, visit));
}

// ParsingContext is an internal const enum. Obtain its ordinal values from
// the pinned source and cross-check each selected emitted numeric case label.
const enums = new Map([["ModuleKind", ts.ModuleKind], ["ScriptKind", ts.ScriptKind], ["SyntaxKind", ts.SyntaxKind], ["CharacterCodes", ts.CharacterCodes], ["TokenFlags", ts.TokenFlags]]);
// Const enum in the pinned scanner.ts. The bundle inlines these bit masks.
enums.set("EscapeSequenceScanningFlags", {RegularExpression: 4, AnnexB: 8, AnyUnicodeMode: 16,
    AtomEscape: 32, ReportInvalidEscapeErrors: 6, AllowExtendedUnicodeEscape: 17});
for (const [name, source] of [["ParsingContext", "parser.ts"], ["ClassSetExpressionType", "scanner.ts"]]) {
    if (!sites.some(site => site.choice?.startsWith(name + ".") ||
        (name === "ClassSetExpressionType" && site.owner === "scanClassSetSubExpression"))) continue;
    const definitions = [];
    descendants(originals.get(source), node => {
        if (ts.isEnumDeclaration(node) && node.name.text === name) definitions.push(node);
    });
    if (definitions.length !== 1) throw new Error("Missing or ambiguous enum " + name);
    const values = Object.create(null);
    definitions[0].members.forEach((member, i) => {
        if (member.initializer || !ts.isIdentifier(member.name)) throw new Error("Unexpected enum declaration " + name);
        values[member.name.text] = i;
    });
    enums.set(name, values);
}

function predicate(node, site) {
    if (site.choice) {
        if (site.choice === "default" && ts.isDefaultClause(node)) return node.parent.parent.expression;
        if (ts.isCaseClause(node) && tokens(node.expression.getText()) === tokens(site.choice)) {
            if (node.getSourceFile() !== bundle && node.expression.getText() !== site.choice) return undefined;
            if (/^(ParsingContext|ClassSetExpressionType)\./.test(site.choice) && node.getSourceFile() === bundle) {
                const trivia = code.slice(node.expression.end, node.getChildren(bundle)[2].getStart(bundle)).trim();
                if (trivia !== "/* " + site.choice.split(".")[1] + " */") return undefined;
            }
            return node.parent.parent.expression;
        }
        return undefined;
    }
    if (ts.isIfStatement(node)) return node.expression;
    if (ts.isConditionalExpression(node)) return node.condition;
}

function tokens(text) {
    const scanner = ts.createScanner(ts.ScriptTarget.Latest, true, ts.LanguageVariant.Standard, text);
    const result = [];
    for (let t = scanner.scan(); t !== ts.SyntaxKind.EndOfFileToken; t = scanner.scan()) {
        const token = scanner.getTokenText();
        const members = enums.get(result.at(-2));
        if (result.at(-1) === "." && typeof members?.[token] === "number") {
            const value = members[token];
            if (value < 0) result.splice(-2, 2, "-", String(-value));
            else result.splice(-2, 2, String(value));
        } else {
            result.push(token);
        }
    }
    return JSON.stringify(result);
}

function caseValue(text) {
    const parts = JSON.parse(tokens(text));
    if (parts.length === 2 && parts[0] === "-" && /^\d+$/.test(parts[1])) return -Number(parts[1]);
    if (parts.length === 1) {
        if (/^\d+$/.test(parts[0])) return Number(parts[0]);
        if (parts[0].startsWith('"')) return JSON.parse(parts[0]);
    }
    throw new Error("Unsupported switch case " + text);
}

function caseValues(discriminant) {
    return discriminant.parent.caseBlock.clauses.filter(ts.isCaseClause).map(clause => caseValue(clause.expression.getText()));
}

// Match ownership in typescript_inventory.mjs; inline lookahead callbacks
// belong to the named parser routine enclosing them.
function scopeName(node) {
    if (ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node)) return node.name?.getText();
    if (ts.isVariableDeclaration(node) && node.initializer &&
        (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))) return node.name.getText();
}

function enclosingRoutine(node) {
    for (let parent = node.parent; parent; parent = parent.parent) {
        const name = scopeName(parent);
        if (name) return name;
    }
}

function originalCondition(site) {
    const file = originals.get(site.file);
    const [line, column] = site.location.split(":").map(Number);
    const pos = file.getPositionOfLineAndCharacter(line - 1, column - 1);
    let node = ts.getTokenAtPosition(file, pos);
    while (node && !(node.getStart(file) === pos && predicate(node, site))) node = node.parent;
    if (!node) throw new Error("Missing conditional at " + site.location);
    let owner = node.parent;
    while (owner && !scopeName(owner)) owner = owner.parent;
    const start = owner && file.getLineAndCharacterOfPosition(owner.getStart(file));
    if (!owner || scopeName(owner) !== site.owner || (start.line + 1) + ":" + (start.character + 1) !== site.ownerLocation) throw new Error("Unexpected owner at " + site.location);
    const expected = normalizedCondition(node, file, site);
    const candidates = conditions(owner, file, site, expected);
    return {expected, enclosing: enclosingRoutine(owner), ordinal: candidates.indexOf(predicate(node, site)), count: candidates.length,
        values: site.choice === "default" ? caseValues(predicate(node, site)) : null};
}

function normalizedCondition(node, file, site) {
    let expr = predicate(node, site);
    while (ts.isParenthesizedExpression(expr)) expr = expr.expression;
    let condition = expr.getText(file);
    // Reviewed emit substitutions at the pinned parser sites. Keep these
    // local to their predicates so unrelated identifiers remain distinct.
    if (site.file === "checker.ts" && site.owner === "checkGrammarParameterList")
        condition = condition.replace("NodeFlags.Ambient", String(ts.NodeFlags.Ambient))
            .replace("(parameterCount - 1)", "parameterCount - 1");
    if (site.file === "checker.ts" && site.owner === "checkGrammarArrowFunction")
        condition = condition.replace(/Extension\.(Mts|Cts)/g, (_, key) => JSON.stringify(ts.Extension[key]));
    if (site.file === "checker.ts" && site.owner === "checkGrammarForUseStrictSimpleParameterList")
        condition = condition.replace("ScriptTarget.ES2016", String(ts.ScriptTarget.ES2016));
    if (site.file === "parser.ts" && site.owner === "getDeclarationFileExtension" && site.location === "10561:5")
        condition = condition.replace("Extension.Ts", JSON.stringify(ts.Extension.Ts));
    if (site.file === "parser.ts" && site.owner === "createSourceFile" && site.ownerLocation === "1344:1")
        condition = condition.replace("ScriptTarget.JSON", String(ts.ScriptTarget.JSON)).replace("format === undefined", "format === void 0");
    if (site.file === "parser.ts" && site.owner === "parseSourceFile" && site.ownerLocation === "1603:5")
        condition = condition.replace("scriptKind ===", "scriptKind2 ===");
    if (site.file === "scanner.ts" && ["codePointChecked", "charCodeChecked"].includes(site.owner))
        condition = condition.replace(/\bpos\b/g, "pos2");
    if (site.file === "scanner.ts" && site.owner === "getIdentifierToken")
        condition = condition.replace("keyword !== undefined", "keyword !== void 0");
    if (site.file === "scanner.ts" && site.owner === "charSize")
        condition = condition.replace("0x10000", "65536");
    if (site.file === "scanner.ts" && ["skipTrivia", "iterateCommentRanges"].includes(site.owner))
        condition = condition.replace("(isWhiteSpaceLike(ch))", "isWhiteSpaceLike(ch)");
    if (site.file === "scanner.ts" && site.owner === "scanPatternModifiers")
        condition = condition.replace("flag === undefined", "flag === void 0")
            .replace("RegularExpressionFlags.Modifiers", "28").replace("CharacterCodes.EOF", "-1");
    if (site.file === "scanner.ts" && site.owner === "reScanSlashToken")
        condition = condition.replace("CharacterCodes.EOF", "-1").replace(/\breportErrors\b/g, "reportErrors2")
            .replace("flag === undefined", "flag === void 0").replaceAll("RegularExpressionFlags.AnyUnicodeMode", "96");
    if (site.file === "scanner.ts" && site.owner === "scanClassRanges")
        condition = condition.replace("isClassContentExit(ch2)", "isClassContentExit(ch)");
    if (site.file === "scanner.ts" && site.owner === "scanClassSetExpression")
        condition = condition.replace("CharacterCodes.EOF", "-1");
    if (site.file === "scanner.ts" && site.owner === "scanClassSetCharacter")
        condition = condition.replace(/\bch2\b/g, "ch");
    if (site.file === "scanner.ts" && site.owner === "scanCharacterClassEscape")
        condition = condition.replace("propertyName === undefined", "propertyName === void 0")
            .replace("propertyName !== undefined", "propertyName !== void 0");
    if (site.file === "scanner.ts" && site.owner === "scanGroupName")
        condition = condition.replace("topNamedCapturingGroupsScope?.has(tokenValue)",
            "(topNamedCapturingGroupsScope == null ? void 0 : topNamedCapturingGroupsScope.has(tokenValue))")
            .replace("group => group?.has(tokenValue)", "(group2) => group2 == null ? void 0 : group2.has(tokenValue)");
    if (site.file === "scanner.ts" && site.owner === "scanRegularExpressionWorker")
        condition = condition.replace("groupSpecifiers?.has(reference.name)", "(groupSpecifiers == null ? void 0 : groupSpecifiers.has(reference.name))");
    if (site.file === "scanner.ts" && site.owner === "scanAlternative")
        condition = condition.replace("ScriptTarget.ES2018", String(ts.ScriptTarget.ES2018)).replace(/\bmin\b/g, "min2")
            .replace("pos === start + 1", "pos === start3 + 1");
    if (site.file === "scanner.ts" && site.owner === "isConflictMarkerTrivia")
        condition = condition.replace("(pos + mergeConflictMarkerLength)", "pos + mergeConflictMarkerLength");
    if (site.file === "scanner.ts" && site.owner === "scanConflictMarkerTrivia" && condition === "error")
        condition = "error2";
    if (site.file === "scanner.ts" && site.owner === "lookupInUnicodeMap")
        condition = condition.replace(/\bmap\b/g, "map2");
    if (site.file === "scanner.ts" && ["isUnicodeIdentifierStart", "isUnicodeIdentifierPart"].includes(site.owner))
        condition = condition.replace("languageVersion! >= ScriptTarget.ES2015", "languageVersion >= " + ts.ScriptTarget.ES2015);
    if (site.file === "scanner.ts" && site.owner === "scanIdentifier")
        condition = condition.replace(/\blanguageVersion\b/g, "languageVersion2");
    if (site.file === "scanner.ts" && site.owner === "scan")
        condition = condition.replace(/\b(extendedCookedChar|cookedChar)2\b/g, "$1")
            .replace(/\bskipTrivia\b/g, "skipTrivia2").replace("isJSDoc &&", "isJSDoc2 &&")
            .replace("LanguageVariant.JSX", String(ts.LanguageVariant.JSX))
            .replace(/&&\s*\(tokenFlags & TokenFlags\.PrecedingLineBreak\)/, "&& tokenFlags & TokenFlags.PrecedingLineBreak");
    if (site.file === "scanner.ts" && site.owner === "scan" && ["2091:29", "2099:29", "2377:26"].includes(site.location))
        condition = condition.replace(/\bch2\b/g, "ch");
    if (site.file === "scanner.ts" && site.owner === "scanHexDigits" && site.location === "1403:18")
        condition = condition.replace("(ch >= CharacterCodes._0 && ch <= CharacterCodes._9)", "ch >= CharacterCodes._0 && ch <= CharacterCodes._9")
            .replace("(ch >= CharacterCodes.a && ch <= CharacterCodes.f)", "ch >= CharacterCodes.a && ch <= CharacterCodes.f");
    if (site.file === "scanner.ts" && site.owner === "scanExtendedUnicodeEscape")
        condition = condition.replace("escapedValue > 0x10FFFF", "escapedValue > 1114111");
    if (site.file === "scanner.ts" && site.owner === "scanEscapeSequence")
        condition = condition.replace(/0xD(?:800|BFF|C00|FFF)\b/g, bound => String(Number(bound)));
    if (site.file === "scanner.ts" && site.owner === "scanString" && condition === "ch === quote") condition = "ch === quote2";
    if (site.file === "scanner.ts" && site.owner === "scanNumber")
        condition = condition.replace("decimalFragment !== undefined", "decimalFragment !== void 0");
    if (site.file === "scanner.ts" && site.owner === "checkForIdentifierStartAfterNumericLiteral")
        condition = condition.replace("length === 1", "length3 === 1");
    if (site.file === "parser.ts" && ["parseBinaryExpressionRest", "parseThrowStatement"].includes(site.owner)
        && condition === "scanner.hasPrecedingLineBreak()") condition = "scanner2.hasPrecedingLineBreak()";
    if (site.file === "parser.ts" && site.owner === "extractPragmas")
        condition = condition.replace("pragma.kind! & PragmaKindFlags.TripleSlashXML", "pragma.kind & " + ts.PragmaKindFlags.TripleSlashXML);
    if (site.file === "parser.ts" && site.owner === "speculationHelper")
        condition = condition.replaceAll("SpeculationKind.TryParse", "0").replaceAll("SpeculationKind.Reparse", "2");
    if (site.file === "parser.ts" && ["nextToken", "nextTokenIsOnSameLineAndCanFollowModifier"].includes(site.owner))
        condition = condition.replaceAll("scanner.", "scanner2.");
    if (site.file === "parser.ts" && site.owner === "isUnambiguouslyIndexSignature")
        condition = condition.replace(/\bisIdentifier\(/g, "isIdentifier2(");
    if (site.file === "parser.ts" && site.owner === "internIdentifier")
        condition = condition.replace("identifier === undefined", "identifier === void 0");
    if (site.file === "parser.ts" && site.owner === "createIdentifier")
        condition = condition.replace(/\bscanner\./g, "scanner2.").replace(/\bisIdentifier\b/g, "isIdentifier3");
    if (site.owner === "isStartOfExpression" && condition === "isBinaryOperator()") condition = "isBinaryOperator2()";
    if (site.file === "parser.ts" && ["currentNode", "isReusableParsingContext", "canReuseNode"].includes(site.owner))
        condition = condition.replace(/\bparsingContext\b/g, "parsingContext2")
            .replace("node.jsDoc?.jsDocCache", "((_a = node.jsDoc) == null ? void 0 : _a.jsDocCache)");
    if (site.file === "parser.ts" && site.owner === "createSourceFile" && site.ownerLocation === "1978:5")
        condition = condition.replace("TransformFlags.ContainsPossibleTopLevelAwait", String(ts.TransformFlags.ContainsPossibleTopLevelAwait));
    if (site.owner === "reparseTopLevelAwait")
        condition = condition.replace("scanner.getTokenFullStart()", "scanner2.getTokenFullStart()");
    if (["findNextStatementWithAwait", "findNextStatementWithoutAwait"].includes(site.owner))
        condition = condition.replace("statements[i]", "statements2[i]");
    if (site.owner === "parseFunctionDeclaration")
        condition = condition.replace(/ModifierFlags\.(Default|Async|Export)/g, (_, key) => String(ts.ModifierFlags[key]));
    if (site.owner === "parseFunctionBlockOrSemicolon") condition = condition.replace("SignatureFlags.Type", "4");
    if (site.owner === "parseObjectLiteralElement" && condition === "isShorthandPropertyAssignment")
        condition = "isShorthandPropertyAssignment2";
    if (site.owner === "parseExpressionOrLabeledStatement")
        condition = condition.replace("isIdentifierNode(expression)", "isIdentifier(expression)");
    if (site.owner === "parseVariableDeclaration")
        condition = condition.replace("scanner.hasPrecedingLineBreak()", "scanner2.hasPrecedingLineBreak()");
    if (site.owner === "parseThrowStatement" && condition === "expression === undefined") condition = "expression === void 0";
    if (site.file === "parser.ts" && site.owner === "isDeclaration")
        condition = condition.replace(/\bcurrentToken\b/g, "currentToken2").replace("scanner.hasPrecedingLineBreak()", "scanner2.hasPrecedingLineBreak()");
    if (site.owner === "parseModuleReference") condition = condition.replace("isExternalModuleReference()", "isExternalModuleReference2()");
    if (["parseExportDeclaration", "tryParseImportAttributes", "parseImportType"].includes(site.owner)) {
        condition = condition.replace(/\bcurrentToken\b/g, "currentToken2").replace("scanner.hasPrecedingLineBreak()", "scanner2.hasPrecedingLineBreak()");
        if (site.location === "8716:13") condition = condition.replace(
            "(token() === SyntaxKind.StringLiteral && !scanner2.hasPrecedingLineBreak())",
            "token() === SyntaxKind.StringLiteral && !scanner2.hasPrecedingLineBreak()");
    }
    if (site.owner === "parseImportDeclarationOrImportEqualsDeclaration") {
        condition = condition.replaceAll("isIdentifier()", "isIdentifier2()")
            .replace("identifier?.escapedText", "(identifier == null ? void 0 : identifier.escapedText)");
    }
    if (site.owner === "parsePropertyAccessExpressionRest")
        condition = condition.replace(/\bisOptionalChain\b/g, "isOptionalChain2");
    if (["parseMemberExpressionRest", "parseRightSideOfDot", "parseSemicolonAfterPropertyName"].includes(site.owner))
        condition = condition.replace("scanner.hasPrecedingLineBreak()", "scanner2.hasPrecedingLineBreak()");
    if (["parseTaggedTemplateRest", "tryReparseOptionalChain"].includes(site.owner))
        condition = condition.replace("NodeFlags.OptionalChain", String(ts.NodeFlags.OptionalChain));
    if (site.owner === "parseLeftHandSideExpressionOrHigher")
        condition = condition.replace("(expression as MetaProperty).name", "expression.name");
    if (site.owner === "parseSuperExpression") condition = condition.replace("!== undefined", "!== void 0");
    if (["parsePrimaryExpression", "parseTemplateHead"].includes(site.owner))
        condition = condition.replace("scanner.getTokenFlags()", "scanner2.getTokenFlags()")
            .replace("TokenFlags.IsInvalid", String(ts.TokenFlags.IsInvalid));
    if (["parseLiteralLikeNode", "getTemplateLiteralRawText", "parseIdentifierNameErrorOnUnicodeEscapeSequence"].includes(site.owner))
        condition = condition.replaceAll("scanner.", "scanner2.");
    if (site.owner === "parseJsxChild" && condition === "token") condition = "token2";
    if (site.owner === "parseJsxTagName" && condition === "isThis") condition = "isThis2";
    if (site.owner === "parseJsxChildren") condition = condition.replace("child?.kind", "(child == null ? void 0 : child.kind)");
    if (site.owner === "parseJsxElementOrSelfClosingElementOrFragment")
        condition = condition.replace("lastChild?.kind", "(lastChild == null ? void 0 : lastChild.kind)");
    if (["parseJsxExpression", "parseJsxOpeningOrSelfClosingElementOrOpeningFragment", "parseJsxClosingElement"].includes(site.owner))
        condition = condition.replace("/*diagnosticMessage*/ undefined", "void 0");
    if (["isUpdateExpression", "parseSimpleUnaryExpression", "parseUpdateExpression"].includes(site.owner))
        condition = condition.replace("LanguageVariant.JSX", String(ts.LanguageVariant.JSX))
            .replace("isAwaitExpression()", "isAwaitExpression2()").replace("scanner.hasPrecedingLineBreak()", "scanner2.hasPrecedingLineBreak()");
    if (site.owner === "parseAssignmentExpressionOrHigher")
        condition = condition.replace("isYieldExpression()", "isYieldExpression2()");
    if (site.owner === "parseYieldExpression") condition = condition.replace("scanner.", "scanner2.");
    if (["tryParseParenthesizedArrowFunctionExpression", "tryParseAsyncSimpleArrowFunctionExpression"].includes(site.owner))
        condition = condition.replace("Tristate.False", "0").replace("Tristate.True", "1");
    if (site.owner === "isParenthesizedArrowFunctionExpressionWorker")
        condition = condition.replace("scanner.", "scanner2.").replace(/\bfirst\b/g, "first2")
            .replace("isIdentifier()", "isIdentifier2()").replace("LanguageVariant.JSX", String(ts.LanguageVariant.JSX));
    if (site.owner === "parsePossibleParenthesizedArrowFunctionExpression" && condition === "notParenthesizedArrow?.has(tokenPos)")
        condition = "notParenthesizedArrow == null ? void 0 : notParenthesizedArrow.has(tokenPos)";
    if (site.owner === "isUnParenthesizedAsyncArrowFunctionWorker")
        condition = condition.replace("scanner.hasPrecedingLineBreak()", "scanner2.hasPrecedingLineBreak()");
    if (site.owner === "parseParametersWorker")
        condition = condition.replace("SignatureFlags.JSDoc", "32");
    if (site.owner === "parseTypePredicatePrefix")
        condition = condition.replace("scanner.hasPrecedingLineBreak()", "scanner2.hasPrecedingLineBreak()");
    if (["parseNonArrayType", "parseTypeArgumentsOfTypeReference", "parseTypeQuery"].includes(site.owner))
        condition = condition.replace("scanner.", "scanner2.");
    if (site.owner === "parseType")
        condition = condition.replace("NodeFlags.TypeExcludesFlags", String(ts.NodeFlags.TypeExcludesFlags))
            .replace("scanner.hasPrecedingLineBreak()", "scanner2.hasPrecedingLineBreak()");
    if (site.owner === "skipParameterStart") condition = condition.replace("isIdentifier()", "isIdentifier2()");
    if (site.owner === "parseHeritageClauses") condition = condition.replace("isHeritageClause()", "isHeritageClause2()");
    if (site.owner === "isClassMemberStart" && condition === "idToken !== undefined") condition = "idToken !== void 0";
    if (site.owner === "parsePropertyDeclaration")
        condition = condition.replace("scanner.hasPrecedingLineBreak()", "scanner2.hasPrecedingLineBreak()");
    if (site.owner === "parseModuleOrNamespaceDeclaration")
        condition = condition.replace("NodeFlags.NestedNamespace", String(ts.NodeFlags.NestedNamespace));
    if (site.owner === "parseTypeAliasDeclaration") condition = condition.replace("scanner.", "scanner2.");
    if (site.owner === "parseErrorForMissingSemicolonAfter")
        condition = condition.replace("isIdentifierNode(node)", "isIdentifier(node)");
    if (site.owner === "isListElement") condition = condition.replace(/\bparsingContext\b/g, "parsingContext2");
    if (["isInSomeParsingContext", "parseList", "parseDelimitedList"].includes(site.owner))
        condition = condition.replace(/\bisListElement\(/g, "isListElement2(").replace(/scanner\./g, "scanner2.");
    if (site.owner === "isInSomeParsingContext" && condition === "parsingContext & (1 << kind)")
        condition = "parsingContext & 1 << kind";
    return tokens(condition);
}

function conditions(owner, file, site, expected) {
    const matches = [];
    function visit(n) {
        if (n !== owner && scopeName(n)) return;
        if (predicate(n, site) && normalizedCondition(n, file, site) === expected) matches.push(predicate(n, site));
        ts.forEachChild(n, visit);
    }
    visit(owner);
    return matches;
}

function emittedOwner(site) {
    if (site.file === "scanner.ts" && site.owner === "error" && site.ownerLocation === "1162:5") return "error2";
    if (site.file === "parser.ts" && site.owner === "createSourceFile" && site.ownerLocation === "1978:5") return "createSourceFile2";
    if (site.file === "parser.ts" && site.owner === "parseJsonText" && site.ownerLocation === "1646:5") return "parseJsonText2";
    if (site.file === "parser.ts" && site.owner === "currentNode" && site.ownerLocation === "1961:9") return "currentNode2";
    if (site.file === "parser.ts" && ["isDeclaration", "isIdentifier", "isAwaitExpression", "isYieldExpression", "isBinaryOperator", "isListElement"].includes(site.owner)) return site.owner + "2";
    return site.owner;
}
const wanted = new Set(sites.map(emittedOwner));
const owners = new Map();
descendants(bundle, node => {
    if (!ts.isFunctionDeclaration(node) || !wanted.has(node.name?.text)) return;
    const name = node.name.text;
    if (!owners.has(name)) owners.set(name, []);
    owners.get(name).push(node);
});

const edits = sites.map((site, id) => {
    const {expected, ordinal, count, values, enclosing} = originalCondition(site);
    let candidates = owners.get(emittedOwner(site)) || [];
    if (candidates.length > 1) candidates = candidates.filter(node => enclosingRoutine(node) === enclosing);
    if (candidates.length !== 1) throw new Error("Missing or ambiguous emitted function " + site.owner);
    const [owner] = candidates;
    const matches = conditions(owner, bundle, site, expected);
    if (ordinal < 0 || matches.length !== count) throw new Error("Unmatched condition at " + site.location);
    if (values && JSON.stringify(values) !== JSON.stringify(caseValues(matches[ordinal])))
        throw new Error("Emitted switch labels differ at " + site.location);
    const matchedValue = site.choice && site.choice !== "default" ? caseValue(site.choice) : null;
    return {caseValues: values, matchedValue, start: matches[ordinal].getStart(bundle), end: matches[ordinal].end, id};
});
// Insert wrappers at the original positions. At a shared start position an
// enclosing if-test must wrap the first operand of its nested ternary.
const events = new Map();
function event(pos) {
    if (!events.has(pos)) events.set(pos, {open: [], close: 0});
    return events.get(pos);
}
for (const edit of edits) {
    event(edit.start).open.push(edit);
    event(edit.end).close++;
}
const chunks = [];
let cursor = 0;
for (const pos of [...events.keys()].sort((a,b) => a - b)) {
    const {open, close} = events.get(pos);
    chunks.push(code.slice(cursor, pos), "))".repeat(close));
    for (const {id} of open.sort((a,b) => b.end - a.end))
        chunks.push("globalThis.orionBranch(" + id + ", (");
    cursor = pos;
}
chunks.push(code.slice(cursor));
const patched = chunks.join("");
let seen;
const instance = new Module(compiler);
instance.filename = compiler;
instance.paths = module.paths;
globalThis.orionBranch = (id, value) => {
    const choice = sites[id].choice;
    if (seen && !choice) seen.add(id + ":" + Boolean(value));
    // Observe the switch discriminant, not statement entry: a fallthrough
    // must never count as selecting the following case.
    if (seen && choice) {
        const selected = choice === "default" ? !edits[id].caseValues.includes(value) : value === edits[id].matchedValue;
        if (selected) seen.add(id + ":" + choice);
    }
    return value;
};
instance._compile(patched, compiler);
process.stdout.write(JSON.stringify(cases.map(({source, name, projection, options: config, target = "ESNext"}) => {
    seen = new Set();
    if (projection === "project config") {
        const {error} = instance.exports.parseConfigFileTextToJson(name, source);
        return {hits: [...seen], parse: error ? [[error.code, Array.from(source.slice(0, error.start)).length,
            Array.from(source.slice(error.start, error.start + error.length)).length]] : []};
    }
    const compilerApi = instance.exports;
    const implied = projection === "implied file context";
    const options = config ? compilerApi.convertCompilerOptionsFromJson(config, ".").options : {target: ts.ScriptTarget[target]};
    const language = implied ? {languageVersion: options.target,
        impliedNodeFormat: compilerApi.getImpliedNodeFormatForFile(name, undefined, compilerApi.sys, options),
        setExternalModuleIndicator: compilerApi.getSetExternalModuleIndicator(options)} : options.target;
    const f = compilerApi.createSourceFile(name, source, projection === "project source" ? ts.ScriptTarget.JSON : language, !implied);
    if (projection === "tokens and expression") {
        // The parser skips trivia. Its scanner can also return the trivia tokens.
        const scanner = instance.exports.createScanner(ts.ScriptTarget[target], false, ts.LanguageVariant.Standard, source);
        while (scanner.scan() !== ts.SyntaxKind.EndOfFileToken) {}
    }
    if (["regexp", "regexp spans"].includes(projection)) {
        // The syntax parser defers pattern checking. Exercise the same
        // pattern-checking scanner entry point as the unmodified AST oracle.
        descendants(f, node => {
            if (!ts.isRegularExpressionLiteral(node)) return;
            const scanner = instance.exports.createScanner(ts.ScriptTarget[target], true, ts.LanguageVariant.Standard, node.getText(f));
            scanner.scan();
            scanner.reScanSlashToken(true);
        });
    }
    const location = projection === "diagnostic location" && f.parseDiagnostics.length
        ? f.getLineAndCharacterOfPosition(f.parseDiagnostics[0].start) : undefined;
    const grammar = projection === "import grammar" ? importGrammarDiagnostics(compilerApi, f, options) :
        projection === "function grammar" ? functionGrammarDiagnostics(compilerApi, f) : undefined;
    return {hits: [...seen], location, grammar, parse: f.parseDiagnostics.map(d => [d.code, Array.from(source.slice(0, d.start)).length,
        Array.from(source.slice(d.start, d.start + d.length)).length])};
})));
