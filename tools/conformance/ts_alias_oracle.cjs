// Independent compiler AST projections for aliases, import types, and index signatures.
const ts = require(process.argv[1]);
const cases = JSON.parse(require("node:fs").readFileSync(0, "utf8"));

function key(n) {
    if (ts.isArrayBindingPattern(n)) return ["ArrayPattern", n.elements.map(e => ts.isOmittedExpression(e) ? null : key(e))];
    if (ts.isObjectBindingPattern(n)) return ["ObjectPattern", n.elements.map(e =>
        e.dotDotDotToken ? key(e) : ["property", key(e.propertyName || e.name), key(e)])];
    if (ts.isBindingElement(n)) {
        const binding = n.initializer ? ["default", key(n.name), operand(n.initializer)] : key(n.name);
        return n.dotDotDotToken ? ["rest", binding] : binding;
    }
    if (ts.isArrayLiteralExpression(n)) return ["ArrayExpression", n.elements.map(e => ts.isOmittedExpression(e) ? null : key(e))];
    if (ts.isObjectLiteralExpression(n)) return ["ObjectExpression", n.properties.map(key)];
    if (ts.isPropertyAssignment(n)) return ["property", key(n.name), key(n.initializer)];
    if (ts.isShorthandPropertyAssignment(n)) return ["property", key(n.name), key(n.name)];
    if (ts.isComputedPropertyName(n)) return ["computed", operand(n.expression)];
    if (ts.isPropertyAccessExpression(n)) return ["access", key(n.expression), key(n.name)];
    if (ts.isThisTypeNode(n)) return ["id", "this"];
    if (ts.isBinaryExpression(n)) return ["binary", n.operatorToken.getText(), key(n.left), key(n.right)];
    if (ts.isPrivateIdentifier(n)) return ["private", n.text.slice(1)];
    if (ts.isIdentifier(n)) return ["id", n.text];
    if (ts.isQualifiedName(n)) return ["qualified", key(n.left), key(n.right)];
    if (ts.isStringLiteral(n)) return ["string", n.text];
    if (ts.isBigIntLiteral(n)) return ["bigint", n.getText()];
    if (ts.isNumericLiteral(n)) return ["number", n.getText()];
    throw new Error("unmapped name: " + ts.SyntaxKind[n.kind]);
}
function params(n) {
    return (n.typeParameters || []).map(p => {
        const record = [p.name.text, (p.modifiers || []).map(m => m.getText()), type(p.constraint), type(p.default)];
        if (p.expression) record.push(operand(p.expression));
        return record;
    });
}
function parameter(p) {
    const decorators = [], modifiers = [];
    for (const item of p.modifiers || []) {
        if (ts.isDecorator(item)) decorators.push([modifiers.length, operand(item.expression)]);
        else modifiers.push(item.getText());
    }
    return [key(p.name), !!p.questionToken, !!p.dotDotDotToken, type(p.type),
            modifiers, p.initializer ? operand(p.initializer) : null, decorators];
}
function signature(n) {
    return [params(n), n.parameters.map(parameter), type(n.type)];
}
function member(n) {
    if (ts.isIndexSignatureDeclaration(n)) return ["indexSignature",
        (n.modifiers || []).some(m => m.kind === ts.SyntaxKind.ReadonlyKeyword),
        (n.modifiers || []).some(m => m.kind === ts.SyntaxKind.StaticKeyword),
        n.parameters.map(parameter), type(n.type)];
    if (ts.isPropertySignature(n)) {
        const name = ts.isComputedPropertyName(n.name) ? ["computed", operand(n.name.expression)] : key(n.name);
        const tree = ["property", name, !!n.questionToken,
            (n.modifiers || []).some(m => m.kind === ts.SyntaxKind.ReadonlyKeyword), type(n.type)];
        if (n.initializer) tree.push(operand(n.initializer));
        return tree;
    }
    if (ts.isGetAccessorDeclaration(n) || ts.isSetAccessorDeclaration(n))
        return [ts.isGetAccessorDeclaration(n) ? "get" : "set", key(n.name), ...signature(n)];
    if (ts.isMethodSignature(n)) return ["method", key(n.name), !!n.questionToken, ...signature(n)];
    if (ts.isConstructSignatureDeclaration(n)) return ["construct", ...signature(n)];
    if (ts.isCallSignatureDeclaration(n)) return ["call", ...signature(n)];
    throw new Error("unmapped member: " + ts.SyntaxKind[n.kind]);
}
function templateCooked(token) {
    return token.templateFlags & ts.TokenFlags.ContainsInvalidEscape ? null : token.text;
}
function type(n) {
    if (!n) return null;
    if (ts.isJSDocNamepathType(n)) return ["JSDocNamepathType", n.getText()];
    if (ts.isJSDocAllType(n) || ts.isJSDocUnknownType(n)) return [ts.SyntaxKind[n.kind]];
    if (ts.isJSDocNullableType(n) || ts.isJSDocNonNullableType(n)) return [ts.SyntaxKind[n.kind], n.postfix, type(n.type)];
    if (ts.isJSDocVariadicType(n) || ts.isJSDocOptionalType(n)) return [ts.SyntaxKind[n.kind], type(n.type)];
    if (ts.isJSDocFunctionType(n))
        return ["JSDocFunctionType", n.parameters.map(p => [p.name?.text ?? null, type(p.type)]), type(n.type)];
    if (ts.isThisTypeNode(n)) return ["this"];
    if (ts.isTypePredicateNode(n)) return ["predicate", !!n.assertsModifier, key(n.parameterName), type(n.type)];
    if (ts.isConditionalTypeNode(n)) return ["conditional", type(n.checkType), type(n.extendsType), type(n.trueType), type(n.falseType)];
    if (ts.isInferTypeNode(n)) return ["infer", n.typeParameter.name.text, type(n.typeParameter.constraint)];
    if (ts.isTypeOperatorNode(n)) return ["operator", ts.tokenToString(n.operator), type(n.type)];
    if (ts.isIndexedAccessTypeNode(n)) return ["index", type(n.objectType), type(n.indexType)];
    if (ts.isRestTypeNode(n) || ts.isOptionalTypeNode(n)) return [ts.isRestTypeNode(n) ? "rest" : "optional", type(n.type)];
    if (ts.isNamedTupleMember(n)) {
        const member = ["named", key(n.name), !!n.questionToken, type(n.type)];
        return n.dotDotDotToken ? ["rest", member] : member;
    }
    if (ts.isMappedTypeNode(n)) {
        const modifier = token => !token ? false : token.kind === ts.SyntaxKind.PlusToken ? "+" :
            token.kind === ts.SyntaxKind.MinusToken ? "-" : true;
        return ["mapped", key(n.typeParameter.name), type(n.typeParameter.constraint), type(n.nameType),
                modifier(n.readonlyToken), modifier(n.questionToken), type(n.type), (n.members || []).map(member)];
    }
    if (ts.isTypeReferenceNode(n)) return ["ref", key(n.typeName), (n.typeArguments || []).map(type)];
    if (ts.isArrayTypeNode(n)) return ["array", type(n.elementType)];
    if (ts.isTupleTypeNode(n)) return ["tuple", n.elements.map(type)];
    if (ts.isParenthesizedTypeNode(n)) return ["group", type(n.type)];
    if (ts.isUnionTypeNode(n) || ts.isIntersectionTypeNode(n)) return [ts.isUnionTypeNode(n) ? "union" : "intersection", n.types.map(type)];
    if (ts.isTypeLiteralNode(n)) return ["object", n.members.map(member)];
    if (ts.isFunctionTypeNode(n) || ts.isConstructorTypeNode(n)) return [ts.isFunctionTypeNode(n) ? "function" : "constructor", ...signature(n)];
    if (ts.isImportTypeNode(n)) {
        const attrs = n.attributes;
        const options = attrs ? [ts.tokenToString(attrs.token), attrs.elements.map(a => [key(a.name), key(a.value)])] : null;
        return ["import", n.isTypeOf, type(n.argument), options, n.qualifier ? key(n.qualifier) : null,
                (n.typeArguments || []).map(type)];
    }
    if (ts.isTypeQueryNode(n)) return ["typeof", key(n.exprName), (n.typeArguments || []).map(type)];
    if (ts.isTemplateLiteralTypeNode(n)) return ["template", [templateCooked(n.head), ...n.templateSpans.map(s => templateCooked(s.literal))], n.templateSpans.map(s => type(s.type))];
    if (ts.isLiteralTypeNode(n)) {
        if (ts.isNoSubstitutionTemplateLiteral(n.literal)) return ["template", [templateCooked(n.literal)], []];
        if (ts.isStringLiteral(n.literal)) return ["string", n.literal.text];
        if (ts.isPrefixUnaryExpression(n.literal)) return ["prefix", ts.tokenToString(n.literal.operator), key(n.literal.operand)];
        if (ts.isNumericLiteral(n.literal) || ts.isBigIntLiteral(n.literal)) return key(n.literal);
        if (n.literal.kind === ts.SyntaxKind.NullKeyword) return ["keyword", "null"];
        if (n.literal.kind === ts.SyntaxKind.TrueKeyword || n.literal.kind === ts.SyntaxKind.FalseKeyword) return ["boolean", n.literal.kind === ts.SyntaxKind.TrueKeyword];
    }
    const word = ts.tokenToString(n.kind);
    if (word && /Keyword$/.test(ts.SyntaxKind[n.kind])) return ["keyword", word];
    throw new Error("unmapped type: " + ts.SyntaxKind[n.kind]);
}
function bindingNames(n) {
    if (ts.isIdentifier(n)) return n.text;
    if (ts.isBindingElement(n)) {
        let binding = bindingNames(n.name);
        if (n.initializer) binding = ["default", binding];
        return n.dotDotDotToken ? ["rest", binding] : binding;
    }
    if (ts.isArrayBindingPattern(n)) return ["array", n.elements.map(e => ts.isOmittedExpression(e) ? null : bindingNames(e))];
    if (ts.isObjectBindingPattern(n)) return ["object", n.elements.map(bindingNames)];
    throw new Error("unmapped binding: " + ts.SyntaxKind[n.kind]);
}
function branchStatement(n) {
    if (ts.isFunctionDeclaration(n)) return ["function", n.name ? key(n.name) : null, signature(n), n.body ? branchStatement(n.body) : null];
    if (ts.isVariableStatement(n)) return ["VariableDeclaration", declarationListKind(n.declarationList),
        n.declarationList.declarations.map(d => [bindingNames(d.name), d.initializer ? operand(d.initializer) : null])];
    if (ts.isClassDeclaration(n)) return ["ClassDeclaration", n.name ? key(n.name) : null,
        n.members.filter(m => ts.isMethodDeclaration(m) || ts.isGetAccessorDeclaration(m) || ts.isSetAccessorDeclaration(m) || ts.isConstructorDeclaration(m))
            .map(m => [ts.isMethodDeclaration(m) ? "method" : ts.isGetAccessorDeclaration(m) ? "get" : ts.isSetAccessorDeclaration(m) ? "set" : "constructor",
                m.name ? key(m.name) : ["id", "constructor"], m.body ? branchStatement(m.body) : null])];
    if (ts.isInterfaceDeclaration(n) || ts.isTypeAliasDeclaration(n)) {
        const mods = (n.modifiers || []).map(m => ts.isDecorator(m) ? ["decorator", operand(m.expression)] : m.getText());
        if (ts.isInterfaceDeclaration(n)) return ["TSInterfaceDeclaration", n.name ? key(n.name) : null, n.members.map(member), mods];
        return ["TSTypeAliasDeclaration", key(n.name), params(n), type(n.type), mods];
    }
    if (ts.isLabeledStatement(n)) return ["LabeledStatement", key(n.label), branchStatement(n.statement)];
    if (ts.isExportAssignment(n)) return ["export assignment", !!n.isExportEquals, operand(n.expression)];
    if (ts.isNamespaceExportDeclaration(n)) return ["TSNamespaceExportDeclaration", key(n.name)];
    if (ts.isEmptyStatement(n)) return ["EmptyStatement"];
    if (ts.isDebuggerStatement(n)) return ["DebuggerStatement"];
    const binding = moduleBindings(n);
    if (binding) return binding;
    if (ts.isThrowStatement(n)) return ["ThrowStatement", n.expression.pos === n.expression.end ? null : operand(n.expression)];
    if (ts.isForStatement(n) || ts.isForInStatement(n) || ts.isForOfStatement(n)) {
        const init = n.initializer;
        const target = init && ts.isVariableDeclarationList(init)
            ? ["VariableDeclaration", declarationListKind(init),
                init.declarations.map(d => [bindingNames(d.name), d.initializer ? operand(d.initializer) : null])]
            : init ? operand(init) : null;
        if (ts.isForStatement(n)) return ["ForStatement", target, n.condition ? operand(n.condition) : null,
            n.incrementor ? operand(n.incrementor) : null, branchStatement(n.statement)];
        return [ts.SyntaxKind[n.kind], !!n.awaitModifier, target, operand(n.expression), branchStatement(n.statement)];
    }
    if (ts.isWhileStatement(n) || ts.isDoStatement(n))
        return [ts.isDoStatement(n) ? "DoWhileStatement" : "WhileStatement", operand(n.expression), branchStatement(n.statement)];
    if (ts.isWithStatement(n)) return ["WithStatement", operand(n.expression), branchStatement(n.statement)];
    if (ts.isModuleDeclaration(n)) return ["TSModuleDeclaration", key(n.name), n.body ? branchStatement(n.body) : null];
    if (ts.isModuleBlock(n)) return ["TSModuleBlock", n.statements.map(branchStatement)];
    if (ts.isEnumDeclaration(n)) return ["TSEnumDeclaration", key(n.name),
        n.members.map(m => [key(m.name), m.initializer ? operand(m.initializer) : null])];
    if (ts.isTryStatement(n)) {
        const c = n.catchClause, d = c?.variableDeclaration;
        return ["TryStatement", branchStatement(n.tryBlock), c ? [d ? bindingNames(d.name) : null, type(d?.type),
            d?.initializer ? operand(d.initializer) : null, branchStatement(c.block)] : null,
            n.finallyBlock ? branchStatement(n.finallyBlock) : null];
    }
    if (ts.isSwitchStatement(n)) return ["SwitchStatement", operand(n.expression), n.caseBlock.clauses.map(c =>
        [ts.isCaseClause(c) ? operand(c.expression) : null, c.statements.map(branchStatement)])];
    if (ts.isBreakStatement(n) || ts.isContinueStatement(n)) return [ts.SyntaxKind[n.kind], n.label?.text ?? null];
    if (ts.isIfStatement(n)) return ["IfStatement", operand(n.expression), branchStatement(n.thenStatement),
        n.elseStatement ? branchStatement(n.elseStatement) : null];
    if (ts.isBlock(n)) return ["BlockStatement", n.statements.map(branchStatement)];
    if (ts.isReturnStatement(n)) return ["ReturnStatement", n.expression ? operand(n.expression) : null];
    if (ts.isExpressionStatement(n)) return ["ExpressionStatement", operand(n.expression)];
    throw new Error("unmapped branch statement: " + ts.SyntaxKind[n.kind]);
}

function declarationListKind(n) {
    const flags = n.flags & ts.NodeFlags.BlockScoped;
    return flags === ts.NodeFlags.AwaitUsing ? "await using" : flags === ts.NodeFlags.Using ? "using" :
        flags === ts.NodeFlags.Const ? "const" : flags === ts.NodeFlags.Let ? "let" : "var";
}
function moduleBindings(n) {
    if (ts.isImportDeclaration(n)) {
        const clause = n.importClause, specs = [];
        if (clause?.name) specs.push(["default", key(clause.name)]);
        const binds = clause?.namedBindings;
        if (binds && ts.isNamespaceImport(binds)) specs.push(["namespace", key(binds.name)]);
        else if (binds) {
            for (const spec of binds.elements) specs.push(["named", key(spec.propertyName || spec.name), key(spec.name), spec.isTypeOnly]);
        }
        return ["import", operand(n.moduleSpecifier), !!clause?.isTypeOnly, specs,
            clause?.phaseModifier === ts.SyntaxKind.DeferKeyword ? "defer" : null];
    }
    if (ts.isImportEqualsDeclaration(n)) {
        const ref = n.moduleReference;
        return ["alias", key(n.name), n.isTypeOnly, ts.isExternalModuleReference(ref) ?
            ["external", operand(ref.expression)] : key(ref)];
    }
    if (ts.isExportDeclaration(n)) {
        const source = n.moduleSpecifier ? operand(n.moduleSpecifier) : null;
        const list = n.exportClause;
        if (!list || ts.isNamespaceExport(list)) return ["star", source, n.isTypeOnly, list ? key(list.name) : null];
        return ["export", source, n.isTypeOnly, list.elements.map(s => [key(s.propertyName || s.name), key(s.name), s.isTypeOnly])];
    }
    return null;
}

function restBindings(name, trees) {
    if (!name || (!ts.isObjectBindingPattern(name) && !ts.isArrayBindingPattern(name))) return;
    name.elements.forEach((e, index) => {
        if (ts.isOmittedExpression(e)) return;
        if (e.dotDotDotToken) {
            const prop = e.propertyName, computed = !!prop && ts.isComputedPropertyName(prop);
            trees.push([ts.isArrayBindingPattern(name) ? "ArrayPattern" : "ObjectPattern", index,
                name.elements.length, !!name.elements.hasTrailingComma, computed, prop ? operand(computed ? prop.expression : prop) : null,
                bindingNames(e.name), e.initializer ? operand(e.initializer) : null]);
        }
        restBindings(e.name, trees);
    });
}

function heritageRecord(n) {
    const clauses = (n.heritageClauses || []).map(c => [ts.tokenToString(c.token), !!c.types.hasTrailingComma,
        c.types.map(t => [operand(t.expression), t.typeArguments ?
            [t.typeArguments.map(type), !!t.typeArguments.hasTrailingComma] : null])]);
    return [ts.isInterfaceDeclaration(n) ? "interface" : "class", n.name?.text ?? null, clauses];
}

function jsxTree(n) {
    if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n)) {
        const open = n.openingElement || n;
        return ["element", jsxTree(open.tagName), ts.isJsxSelfClosingElement(n),
            open.typeArguments ? open.typeArguments.map(type) : null, open.attributes.properties.map(jsxTree),
            (n.children || []).map(jsxTree), n.closingElement ? jsxTree(n.closingElement.tagName) : null];
    }
    if (ts.isJsxFragment(n)) return ["fragment", n.children.map(jsxTree)];
    if (ts.isIdentifier(n)) return ["id", n.text];
    if (n.kind === ts.SyntaxKind.ThisKeyword) return ["id", "this"];
    if (ts.isJsxNamespacedName(n)) return ["namespace", jsxTree(n.namespace), jsxTree(n.name)];
    if (ts.isPropertyAccessExpression(n)) return ["member", jsxTree(n.expression), jsxTree(n.name)];
    if (ts.isJsxSpreadAttribute(n)) return ["spread attribute", operand(n.expression)];
    if (ts.isJsxAttribute(n)) return ["attribute", jsxTree(n.name), n.initializer ? jsxTree(n.initializer) : null];
    if (ts.isJsxExpression(n)) return [n.dotDotDotToken ? "spread child" : "container", n.expression ? operand(n.expression) : null];
    if (ts.isJsxText(n)) return ["text", n.text];
    return operand(n);
}
function operand(n) {
    if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n) || ts.isJsxFragment(n)) return jsxTree(n);
    if (ts.isParenthesizedExpression(n)) return operand(n.expression);
    if (ts.isPropertyAccessExpression(n) || ts.isElementAccessExpression(n)) {
        const index = ts.isElementAccessExpression(n);
        return [index ? "index" : "access", !!(n.flags & ts.NodeFlags.OptionalChain), !!n.questionDotToken, operand(n.expression), operand(index ? n.argumentExpression : n.name)];
    }
    if (n.kind === ts.SyntaxKind.ImportKeyword) return ["keyword", "import"];
    if (ts.isImportCall(n)) {
        const phase = ts.isMetaProperty(n.expression) ? "defer" : null;
        return ["import", phase, !!(n.flags & ts.NodeFlags.OptionalChain), !!n.questionDotToken,
            (n.typeArguments || []).map(type), n.arguments.map(operand), !!n.arguments.hasTrailingComma];
    }
    if (ts.isCallExpression(n) || ts.isNewExpression(n)) {
        const shape = [ts.isCallExpression(n) ? "call" : "new", !!(n.flags & ts.NodeFlags.OptionalChain),
            !!n.questionDotToken, operand(n.expression), (n.typeArguments || []).map(type), (n.arguments || []).map(operand)];
        if (ts.isNewExpression(n)) shape.push(n.arguments !== undefined);
        shape.push(!!n.arguments?.hasTrailingComma);
        return shape;
    }
    if (ts.isTemplateExpression(n) || ts.isNoSubstitutionTemplateLiteral(n)) {
        const spans = n.templateSpans || [];
        return ["template", [templateCooked(n.head || n), ...spans.map(s => templateCooked(s.literal))], spans.map(s => operand(s.expression))];
    }
    if (ts.isTaggedTemplateExpression(n)) {
        const spans = n.template.templateSpans || [];
        return ["tag", !!(n.flags & ts.NodeFlags.OptionalChain), !!n.questionDotToken, operand(n.tag),
                (n.typeArguments || []).map(type), [templateCooked(n.template.head || n.template), ...spans.map(s => templateCooked(s.literal))],
                spans.map(s => operand(s.expression))];
    }
    if (ts.isExpressionWithTypeArguments(n)) return ["instantiation", operand(n.expression), (n.typeArguments || []).map(type)];
    if (ts.isNonNullExpression(n)) return ["nonNull", !!(n.flags & ts.NodeFlags.OptionalChain), operand(n.expression)];
    if (ts.isAsExpression(n)) return ["TSAsExpression", operand(n.expression), type(n.type)];
    if (ts.isSatisfiesExpression(n)) return ["TSSatisfiesExpression", operand(n.expression), type(n.type)];
    if (ts.isTypeAssertionExpression(n)) return ["TSTypeAssertion", operand(n.expression), type(n.type)];
    if (ts.isVoidExpression(n) || ts.isTypeOfExpression(n) || ts.isDeleteExpression(n))
        return ["unary", ts.isVoidExpression(n) ? "void" : ts.isTypeOfExpression(n) ? "typeof" : "delete", true, operand(n.expression)];
    if (ts.isBinaryExpression(n)) return ["binary", n.operatorToken.getText(), operand(n.left), operand(n.right)];
    if (ts.isPostfixUnaryExpression(n) || ts.isPrefixUnaryExpression(n))
        return ["unary", ts.tokenToString(n.operator), ts.isPrefixUnaryExpression(n), operand(n.operand)];
    if (n.kind === ts.SyntaxKind.ThisKeyword || n.kind === ts.SyntaxKind.SuperKeyword) return ["keyword", n.getText()];
    if (ts.isArrayLiteralExpression(n)) return ["array", n.elements.map(e => ts.isOmittedExpression(e) ? null : operand(e))];
    if (ts.isObjectLiteralExpression(n)) return ["object", n.properties.map(operand)];
    if (ts.isRegularExpressionLiteral(n)) {
        const raw = n.getText(), end = raw.lastIndexOf("/");
        return ["regexp", raw.slice(1, end), raw.slice(end + 1)];
    }
    if (ts.isMethodDeclaration(n) || ts.isGetAccessorDeclaration(n) || ts.isSetAccessorDeclaration(n)) {
        const computed = ts.isComputedPropertyName(n.name);
        return ["method", ts.isMethodDeclaration(n) ? "init" : ts.isGetAccessorDeclaration(n) ? "get" : "set",
            computed, operand(computed ? n.name.expression : n.name), signature(n), !!n.body];
    }
    if (ts.isPropertyAssignment(n)) {
        const computed = ts.isComputedPropertyName(n.name);
        return ["prop", computed, operand(computed ? n.name.expression : n.name), operand(n.initializer)];
    }
    if (ts.isShorthandPropertyAssignment(n)) return ["prop", false, key(n.name), n.objectAssignmentInitializer ?
        ["binary", "=", key(n.name), operand(n.objectAssignmentInitializer)] : key(n.name)];
    if (ts.isSpreadElement(n) || ts.isSpreadAssignment(n)) return ["spread", operand(n.expression)];
    if (ts.isClassExpression(n)) {
        const members = n.members.map(m => {
            const kind = ts.isConstructorDeclaration(m) ? "constructor" : ts.isGetAccessorDeclaration(m) ? "get" :
                ts.isSetAccessorDeclaration(m) ? "set" : ts.isMethodDeclaration(m) ? "method" :
                ts.isPropertyDeclaration(m) ? "PropertyDefinition" : ts.isClassStaticBlockDeclaration(m) ? "StaticBlock" : ts.SyntaxKind[m.kind];
            const computed = m.name && ts.isComputedPropertyName(m.name);
            return [kind, (m.modifiers || []).some(mod => mod.kind === ts.SyntaxKind.StaticKeyword), !!computed,
                    m.name ? operand(computed ? m.name.expression : m.name) : null];
        });
        return ["class", heritageRecord(n), params(n), members];
    }
    if (ts.isArrowFunction(n) || ts.isFunctionExpression(n)) return [ts.isArrowFunction(n) ? "arrow" : "function",
        !!n.modifiers?.some(m => m.kind === ts.SyntaxKind.AsyncKeyword), !!n.asteriskToken,
        signature(n), ts.isBlock(n.body) ? n.body.statements.map(statementShape) : operand(n.body)];
    if (ts.isConditionalExpression(n)) return ["conditional", operand(n.condition), operand(n.whenTrue), operand(n.whenFalse)];
    if (n.kind === ts.SyntaxKind.TrueKeyword || n.kind === ts.SyntaxKind.FalseKeyword || n.kind === ts.SyntaxKind.NullKeyword)
        return ["literal", n.kind === ts.SyntaxKind.NullKeyword ? null : n.kind === ts.SyntaxKind.TrueKeyword];
    if (ts.isYieldExpression(n)) return ["yield", !!n.asteriskToken, n.expression ? operand(n.expression) : null];
    if (ts.isAwaitExpression(n)) return ["await", operand(n.expression)];
    if (ts.isMetaProperty(n)) return ["meta", ts.tokenToString(n.keywordToken), n.name.text];
    return key(n);
}

function typeListOwner(n) {
    if (ts.isClassLike(n)) return "class";
    if (ts.isFunctionLike(n) || ts.isFunctionTypeNode(n) || ts.isConstructorTypeNode(n)) return "signature";
    if (ts.isInterfaceDeclaration(n)) return "interface";
    if (ts.isTypeAliasDeclaration(n)) return "alias";
    if (ts.isTypeReferenceNode(n)) return "reference";
    if (ts.isTypeQueryNode(n)) return "query";
    if (ts.isExpressionWithTypeArguments(n)) return ts.isHeritageClause(n.parent) ? "heritage" : "instantiation";
    if (ts.isCallExpression(n)) return "call";
    if (ts.isNewExpression(n)) return "new";
    if (ts.isTaggedTemplateExpression(n)) return "tag";
    if (ts.isImportTypeNode(n)) return "import type";
    if (ts.isJsxOpeningElement(n) || ts.isJsxSelfClosingElement(n)) return "jsx";
    return ts.SyntaxKind[n.kind];
}

function privateShape(n) {
    if (ts.isPrivateIdentifier(n)) return key(n);
    if (ts.isBinaryExpression(n)) {
        let left = n.left;
        while (ts.isParenthesizedExpression(left)) left = left.expression;
        if (ts.isPrivateIdentifier(left)) return ["left", n.operatorToken.getText(), left.text.slice(1)];
    }
    if (!n.name || !ts.isPrivateIdentifier(n.name)) return null;
    const name = n.name.text.slice(1);
    if (ts.isPropertyAccessExpression(n)) return ["access", name];
    if (ts.isEnumMember(n)) return ["enum", name];
    const isStatic = (n.modifiers || []).some(m => m.kind === ts.SyntaxKind.StaticKeyword);
    const accessor = ts.isGetAccessorDeclaration(n) ? "get" : ts.isSetAccessorDeclaration(n) ? "set" : null;
    if (ts.isPropertyDeclaration(n)) return ["PropertyDefinition", null, isStatic, name];
    if (ts.isPropertySignature(n)) return ["TSPropertySignature", null, isStatic, name];
    if (ts.isMethodSignature(n)) return ["TSMethodSignature", null, isStatic, name];
    if (ts.isObjectLiteralExpression(n.parent)) return ["Property", accessor || "init", false, name];
    if (accessor && (ts.isTypeLiteralNode(n.parent) || ts.isInterfaceDeclaration(n.parent)))
        return ["TSMethodSignature", accessor, isStatic, name];
    return ["MethodDefinition", accessor || "method", isStatic, name,
            (n.modifiers || []).some(m => m.kind === ts.SyntaxKind.AsyncKeyword), !!n.asteriskToken, !!n.body];
}
process.stdout.write(JSON.stringify(cases.map(({name, source, projection, diagnosticSpans, compilerModuleDetection, options: configOptions, target = "ESNext"}) => {
    if (projection === "project config") {
        const {config, error} = ts.parseConfigFileTextToJson(name, source);
        return error ? {invalid: true, diagnostics: [[error.code, Array.from(source.slice(0, error.start)).length,
            Array.from(source.slice(error.start, error.start + error.length)).length]]} : {trees: [config]};
    }
    const options = configOptions ? ts.convertCompilerOptionsFromJson(configOptions, ".").options : {target: ts.ScriptTarget[target]};
    const languageVersion = ts.getEmitScriptTarget(options);
    const implied = projection === "implied file context";
    const language = implied || compilerModuleDetection ? {languageVersion,
        impliedNodeFormat: ts.getImpliedNodeFormatForFile(name, undefined, ts.sys, options),
        setExternalModuleIndicator: ts.getSetExternalModuleIndicator(options)} : languageVersion;
    const f = ts.createSourceFile(name, source, projection === "project source" ? ts.ScriptTarget.JSON : language, !implied);
    if (implied) ts.setParentRecursive(f, false); // getText() in the AST projection needs parents.
    if (projection === "project source") {
        const diagnostics = f.parseDiagnostics.slice();
        const config = ts.convertToObject(f, diagnostics);
        const project = ts.parseConfigFileTextToJson(name, source);
        if (diagnostics.length || project.error || JSON.stringify(config) !== JSON.stringify(project.config))
            throw new Error("Project source witness must match the project configuration reader");
        return {trees: [config]};
    }
    let location, cliLocation;
    if ((projection === "diagnostic location" || (projection === "file context" && diagnosticSpans)) && f.parseDiagnostics.length) {
        const start = f.parseDiagnostics[0].start;
        location = f.getLineAndCharacterOfPosition(start);
        const prefix = source.slice(start - location.character, start);
        cliLocation = [location.line + 1, Array.from(prefix).length + 1];
    }
    if (f.parseDiagnostics.length && !diagnosticSpans) return {invalid: true};
    if (f.parseDiagnostics.length) return {invalid: true, location, cliLocation, firstMessage: f.parseDiagnostics[0].messageText, diagnostics: f.parseDiagnostics.map(d => [
        d.code, Array.from(source.slice(0, d.start)).length, Array.from(source.slice(d.start, d.start + d.length)).length
    ])};
    const trees = [];
    if (projection === "import grammar" || projection === "import diagnostics") {
        const grammar = importGrammarDiagnostics(ts, f, options);
        return {grammar, trees: projection === "import grammar" ? [[f.statements.map(branchStatement), grammar]] : grammar};
    }
    if (projection === "parameter diagnostics" || projection === "generic diagnostics") {
        try {
            return {trees: projection === "parameter diagnostics" ? parameterGrammarDiagnostics(ts, f) : genericGrammarDiagnostics(ts, f)};
        } catch (error) {
            return {checkerFailure: error.message};
        }
    }
    if (projection === "function grammar") {
        const grammar = functionGrammarDiagnostics(ts, f);
        return {grammar, trees: [[f.statements.map(branchStatement), grammar]]};
    }
    if (projection === "file context" || implied) {
        return {trees: [[ts.isExternalModule(f) ? "module" : "script", ts.ScriptKind[f.scriptKind],
            f.isDeclarationFile, f.statements.map(branchStatement)]]};
    }
    if (projection === "tokens and expression") {
        const scanner = ts.createScanner(languageVersion, false, ts.LanguageVariant.Standard, source);
        const tokens = [];
        for (let kind = scanner.scan(); kind !== ts.SyntaxKind.EndOfFileToken; kind = scanner.scan()) {
            if (kind >= ts.SyntaxKind.FirstTriviaToken && kind <= ts.SyntaxKind.LastTriviaToken) continue;
            const start = scanner.getTokenStart();
            tokens.push([scanner.getTokenText(), Array.from(source.slice(0, start)).length, f.getLineAndCharacterOfPosition(start).line + 1]);
        }
        return {trees: f.statements.map(stmt => operand(stmt.expression)), tokens};
    }
    if (projection === "heritage source") {
        trees.push(f.statements.map(n => ts.isExpressionStatement(n) ? ["expression", operand(n.expression)] : statementShape(n)));
    }
    if (projection === "resource statements") {
        return {trees: f.statements.map(stmt => [branchStatement(stmt), (stmt.modifiers || []).map(
            m => ts.isDecorator(m) ? ["decorator", operand(m.expression)] : m.getText())])};
    }
    if (projection === "function source") {
        for (const stmt of f.statements) {
            const fn = ts.isVariableStatement(stmt) ? stmt.declarationList.declarations[0].initializer : stmt;
            trees.push([ts.isFunctionExpression(fn) ? "expression" : "declaration", fn.name?.text ?? null,
                !!fn.modifiers?.some(m => m.kind === ts.SyntaxKind.AsyncKeyword), !!fn.asteriskToken,
                signature(fn), fn.body ? branchStatement(fn.body) : null]);
        }
        return {trees};
    }
    if (projection === "object elements") {
        for (const statement of f.statements) {
            let obj = statement.expression;
            while (ts.isParenthesizedExpression(obj)) obj = obj.expression;
            trees.push(obj.properties.map(member => {
                const modifiers = [], decorators = [];
                for (const m of member.modifiers || []) {
                    if (ts.isDecorator(m)) decorators.push([modifiers.length, operand(m.expression)]);
                    else modifiers.push(m.getText());
                }
                return [operand(member), modifiers, decorators, ts.isShorthandPropertyAssignment(member),
                    !!member.questionToken, !!member.exclamationToken, !!member.asteriskToken, member.body ? branchStatement(member.body) : null];
            }));
        }
        return {trees};
    }
    if (projection === "source references") {
        for (const [kind, refs] of [["path", f.referencedFiles], ["types", f.typeReferenceDirectives], ["lib", f.libReferenceDirectives]]) {
            for (const ref of refs) {
                const record = {kind, value: ref.fileName};
                if (ref.preserve) record.preserve = true;
                if (ref.resolutionMode) record.resolutionMode = ref.resolutionMode === ts.ModuleKind.CommonJS ? "require" : "import";
                trees.push(record);
            }
        }
        for (const dep of f.amdDependencies) trees.push({kind: "amd-dependency", ...dep});
        if (f.moduleName !== undefined) trees.push({kind: "amd-module", name: f.moduleName});
        if (f.hasNoDefaultLib) trees.push({kind: "no-default-lib", value: "true"});
        return {trees};
    }
    const pending = [f];
    try {
        while (pending.length) {
            const n = pending.pop();
            if (projection === "rest binding" && (ts.isVariableDeclaration(n) || ts.isParameter(n)))
                restBindings(n.name, trees);
            if (projection === "decorated parameter" && ts.isParameter(n) && n.modifiers?.some(ts.isDecorator))
                trees.push(parameter(n));
            if (projection === "yield expression" && ts.isYieldExpression(n)) trees.push(operand(n));
            if (projection === "template spelling" && (ts.isTemplateExpression(n) || ts.isTemplateLiteralTypeNode(n)
                || ts.isNoSubstitutionTemplateLiteral(n))) {
                const spans = n.templateSpans || [], fragments = [n.head || n, ...spans.map(s => s.literal)];
                const quasis = fragments.map((f,i) => [f.rawText, templateCooked(f),
                    i === fragments.length - 1]);
                const isType = ts.isTemplateLiteralTypeNode(n) || ts.isLiteralTypeNode(n.parent);
                trees.push([isType ? "type" : "expression", quasis, spans.map(s => isType ? type(s.type) : operand(s.expression))]);
            }
            if (projection === "JSX" && (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n) || ts.isJsxFragment(n))) {
                trees.push(jsxTree(n));
                continue;
            }
            if (projection === "namespace replay" && ts.isExpressionStatement(n) && ts.isSourceFile(n.parent))
                trees.push(["expression", operand(n.expression)]);
            if (["namespace statements", "namespace replay"].includes(projection) && ts.isModuleBlock(n)) {
                trees.push(n.statements.map(stmt => ts.isVariableStatement(stmt)
                    ? [(stmt.declarationList.flags & ts.NodeFlags.Const) ? "const" : (stmt.declarationList.flags & ts.NodeFlags.Let) ? "let" : "var",
                       stmt.declarationList.declarations.map(d => [key(d.name), operand(d.initializer)])] : ts.isModuleDeclaration(stmt) ? statementShape(stmt) : branchStatement(stmt)));
            }
            if (projection === "namespace and enum" && ts.isModuleDeclaration(n)) {
                const kind = n.flags & ts.NodeFlags.GlobalAugmentation ? "global" : n.flags & ts.NodeFlags.Namespace ? "namespace" : "module";
                const content = !n.body ? null : ts.isModuleDeclaration(n.body) ? ["nested", key(n.body.name)] :
                    ["block", n.body.statements.map(statementShape)];
                trees.push(["TSModuleDeclaration", kind, key(n.name), content]);
            }
            if (projection === "namespace and enum" && ts.isEnumDeclaration(n)) {
                const members = n.members.map(m => {
                    const computed = ts.isComputedPropertyName(m.name);
                    return [computed, operand(computed ? m.name.expression : m.name), m.initializer ? operand(m.initializer) : null];
                });
                trees.push(["TSEnumDeclaration", key(n.name), !!n.modifiers?.some(m => m.kind === ts.SyntaxKind.ConstKeyword),
                    !!n.members.hasTrailingComma, members]);
            }
            if (["class members", "class member modifiers", "computed await", "class keyword members"].includes(projection) && ts.isClassLike(n)) {
                const members = [];
                for (const m of n.members) {
                    const mods = (m.modifiers || []).filter(t => !ts.isDecorator(t)).map(t => t.getText());
                    if (projection === "class member modifiers" && !mods.includes("async") && !mods.includes("const")) continue;
                    const kind = ts.isMethodDeclaration(m) ? "method" : ts.isConstructorDeclaration(m) ? "constructor" :
                        ts.isGetAccessorDeclaration(m) ? "get" : ts.isSetAccessorDeclaration(m) ? "set" :
                        ts.isIndexSignatureDeclaration(m) ? "TSIndexSignature" :
                        ts.isClassStaticBlockDeclaration(m) ? "StaticBlock" : ts.isSemicolonClassElement(m) ? "SemicolonClassElement" : "PropertyDefinition";
                    const computed = !!m.name && ts.isComputedPropertyName(m.name);
                    const name = ts.isConstructorDeclaration(m) ? ["id", "constructor"] :
                        m.name ? operand(computed ? m.name.expression : m.name) : null;
                    members.push([kind, mods, computed, name, !!m.questionToken, !!m.exclamationToken, !!m.asteriskToken,
                        !ts.isClassStaticBlockDeclaration(m) && !!m.body, !!m.initializer]);
                    if (projection === "class keyword members") {
                        let index = 0;
                        const decorators = [];
                        for (const modifier of m.modifiers || []) {
                            if (ts.isDecorator(modifier)) decorators.push([index, operand(modifier.expression)]);
                            else index++;
                        }
                        members.at(-1).push(decorators);
                        if (ts.isClassStaticBlockDeclaration(m)) members.at(-1).push(m.body.statements.map(branchStatement));
                        else if (ts.isIndexSignatureDeclaration(m)) members.at(-1).push(member(m));
                    }
                    if (projection === "computed await")
                        members.at(-1).push(m.initializer ? operand(m.initializer) : null,
                            m.body ? m.body.statements.map(branchStatement) : null);
                }
                if (projection !== "class member modifiers") trees.push([ts.isClassDeclaration(n) ? "ClassDeclaration" : "ClassExpression", n.name?.text ?? null, members]);
                else trees.push(...members);
            }
            if (projection === "declaration modifiers" && ts.isStatement(n) && n.modifiers?.length) {
                trees.push([...statementShape(n), n.modifiers.map(m => ts.isDecorator(m) ?
                    ["decorator", operand(m.expression)] : m.getText())]);
            }
            if (projection === "heritage source" && ts.isClassLike(n)) trees.push([heritageRecord(n), !!n.members.isMissingList]);
            if (projection === "heritage" && (ts.isInterfaceDeclaration(n) || ts.isClassLike(n))) {
                trees.push(heritageRecord(n));
            }
            if (projection === "type list" || projection === "empty type list") {
                for (const [kind, list] of [["parameters", n.typeParameters], ["arguments", n.typeArguments]]) {
                    if (list && (projection === "type list" || !list.length))
                        trees.push([typeListOwner(n), kind, list.length, !!list.hasTrailingComma]);
                }
            }
            if (projection === "import type" && ts.isImportTypeNode(n)) {
                trees.push(type(n));
                continue;
            }
            if (projection === "index signature" && ts.isIndexSignatureDeclaration(n)) {
                trees.push(member(n));
                continue;
            }
            if (projection === "property initializer" && ts.isPropertySignature(n) && n.initializer)
                trees.push(member(n));
            if (projection === "type member list" && (ts.isInterfaceDeclaration(n) || ts.isTypeLiteralNode(n))) {
                trees.push([ts.isInterfaceDeclaration(n) ? "interface" : "object",
                    n.members.map(m => [(m.modifiers || []).map(token => token.getText()), member(m)])]);
            }
            if (projection === "branch statement" && ts.isSourceFile(n)) trees.push(...n.statements.map(branchStatement));
            if (projection === "class method signature" && ts.isMethodDeclaration(n) && ts.isClassLike(n.parent))
                trees.push(["method", key(n.name), signature(n)]);
            if (projection === "throw" && ts.isThrowStatement(n)) {
                const missing = n.expression.pos === n.expression.end;
                trees.push(["ThrowStatement", missing ? null : operand(n.expression),
                    missing ? Array.from(source.slice(0, n.expression.pos)).length : null]);
            }
            if (projection === "throw" && ts.isExpressionStatement(n)) trees.push(["ExpressionStatement", operand(n.expression)]);
            if (projection === "for statement" && ts.isForStatement(n)) {
                trees.push(["ForStatement", ...[n.initializer, n.condition, n.incrementor].map(e => e ? operand(e) : null),
                    statementShape(n.statement)[0]]);
            }
            if (projection === "iteration" && (ts.isForOfStatement(n) || ts.isForInStatement(n))) {
                const left = n.initializer;
                const target = ts.isVariableDeclarationList(left) ?
                    [declarationListKind(left), left.declarations.map(d => [bindingNames(d.name), type(d.type),
                        d.initializer ? operand(d.initializer) : null])] : operand(left);
                trees.push([ts.isForOfStatement(n) ? "ForOfStatement" : "ForInStatement", !!n.awaitModifier,
                    target, operand(n.expression), statementShape(n.statement)[0]]);
            }
            if (projection === "declaration list" && ts.isVariableDeclarationList(n)) {
                const kind = declarationListKind(n);
                trees.push([kind, !!n.declarations.hasTrailingComma,
                    n.declarations.map(d => [bindingNames(d.name), !!d.type, !!d.initializer, !!d.exclamationToken])]);
            }
            if (projection === "chain continuation" && (ts.isCallExpression(n) || ts.isPropertyAccessExpression(n)
                || ts.isElementAccessExpression(n) || ts.isTaggedTemplateExpression(n))) {
                let base = n.expression || n.tag;
                while (ts.isParenthesizedExpression(base)) base = base.expression;
                if ((n.flags & ts.NodeFlags.OptionalChain) || ts.isNonNullExpression(base) || ts.isExpressionWithTypeArguments(base))
                    trees.push(operand(n));
            }
            if (projection === "module bindings") {
                const record = moduleBindings(n);
                if (record) {
                    if (n.attributes) record.push([ts.tokenToString(n.attributes.token),
                        n.attributes.elements.map(a => [key(a.name), operand(a.value)])]);
                    trees.push(record);
                }
            }
            if (projection === "target expression" && ts.isExpressionStatement(n) && ts.isSourceFile(n.parent))
                trees.push(operand(n.expression));
            if (["regexp", "regexp spans"].includes(projection) && ts.isRegularExpressionLiteral(n)) {
                const raw = n.getText(), end = raw.lastIndexOf("/");
                let patternError = false;
                const flagOffsets = [], issues = [];
                const scanner = ts.createScanner(languageVersion, true, ts.LanguageVariant.Standard, raw, (diagnostic, length, arg) => {
                    const pos = scanner.getTextPos();
                    if (projection === "regexp spans") {
                        const absolute = n.getStart(f) + pos;
                        issues.push([diagnostic.code, Array.from(source.slice(0, absolute)).length,
                            Array.from(source.slice(absolute, absolute + length)).length, diagnostic.code === 1369 ? arg : null]);
                    }
                    if (pos > end) flagOffsets.push(Array.from(source.slice(0, n.getStart(f) + pos)).length);
                    else patternError = true;
                });
                scanner.scan();
                scanner.reScanSlashToken(true);
                if (projection === "regexp spans") trees.push([raw.slice(1, end), raw.slice(end + 1), issues]);
                else trees.push([raw.slice(1, end), raw.slice(end + 1), !patternError, flagOffsets]);
            }
            if (projection === "definite field" && ts.isPropertyDeclaration(n) && n.exclamationToken) {
                const computed = ts.isComputedPropertyName(n.name);
                trees.push([operand(computed ? n.name.expression : n.name), computed,
                    !!n.modifiers?.some(m => m.kind === ts.SyntaxKind.StaticKeyword), type(n.type),
                    n.initializer ? operand(n.initializer) : null]);
            }
            if (projection === "generator signature" && n.asteriskToken && !n.body) {
                const async = !!n.modifiers?.some(m => m.kind === ts.SyntaxKind.AsyncKeyword);
                if (ts.isFunctionDeclaration(n)) trees.push(["function", n.name ? key(n.name) : null, async, signature(n)]);
                else if (ts.isMethodDeclaration(n) && ts.isClassLike(n.parent)) {
                    const computed = ts.isComputedPropertyName(n.name);
                    trees.push(["method", operand(computed ? n.name.expression : n.name), computed,
                        !!n.modifiers?.some(m => m.kind === ts.SyntaxKind.StaticKeyword), !!n.questionToken, async, signature(n)]);
                }
            }
            if (projection === "bodyless object member" && !n.body && n.parent && ts.isObjectLiteralExpression(n.parent)
                && (ts.isMethodDeclaration(n) || ts.isGetAccessorDeclaration(n) || ts.isSetAccessorDeclaration(n))) {
                const computed = ts.isComputedPropertyName(n.name);
                trees.push([ts.isGetAccessorDeclaration(n) ? "get" : ts.isSetAccessorDeclaration(n) ? "set" : "init",
                    computed, operand(computed ? n.name.expression : n.name), !!n.modifiers?.some(m => m.kind === ts.SyntaxKind.AsyncKeyword),
                    !!n.asteriskToken, !!n.questionToken, !!n.exclamationToken, signature(n)]);
            }
            if (projection === "accessor" && (ts.isGetAccessorDeclaration(n) || ts.isSetAccessorDeclaration(n))) {
                const container = ts.isObjectLiteralExpression(n.parent) ? "Property" :
                    ts.isTypeLiteralNode(n.parent) || ts.isInterfaceDeclaration(n.parent) ? "TSMethodSignature" : "MethodDefinition";
                const computed = ts.isComputedPropertyName(n.name);
                trees.push([container, ts.isGetAccessorDeclaration(n) ? "get" : "set",
                    (n.modifiers || []).filter(m => !ts.isDecorator(m)).map(m => m.getText()), computed,
                    operand(computed ? n.name.expression : n.name), signature(n), !!n.body]);
            }
            if (projection === "parameter lists" && ts.isFunctionLike(n)) {
                trees.push([n.parameters.length, n.parameters.flatMap((p, i) => p.dotDotDotToken ? [i] : []),
                    !!n.parameters.hasTrailingComma]);
            }
            if (projection === "literal and binding lists" && (ts.isArrayLiteralExpression(n) || ts.isArrayBindingPattern(n)
                    || ts.isObjectLiteralExpression(n) || ts.isObjectBindingPattern(n))) {
                const array = ts.isArrayLiteralExpression(n) || ts.isArrayBindingPattern(n);
                const children = ts.isObjectLiteralExpression(n) ? n.properties : n.elements;
                trees.push([array ? "array" : "object", children.length,
                    children.flatMap((child, i) => ts.isOmittedExpression(child) ? [i] : []), !!children.hasTrailingComma]);
            }
            if (projection === "await expression" && ts.isAwaitExpression(n)) trees.push(operand(n));
            if (projection === "call expression" && ts.isCallExpression(n)) trees.push(operand(n));
            if (projection === "new expression" && ts.isNewExpression(n)) trees.push(operand(n));
            if (projection === "meta property" && ts.isMetaProperty(n)) trees.push(operand(n));
            if (projection === "template tag" && ts.isTaggedTemplateExpression(n)) trees.push(operand(n));
            if (projection === "update" && (ts.isPostfixUnaryExpression(n) || ts.isPrefixUnaryExpression(n))
                    && (n.operator === ts.SyntaxKind.PlusPlusToken || n.operator === ts.SyntaxKind.MinusMinusToken))
                trees.push(operand(n));
            if (projection === "assignment" && ts.isBinaryExpression(n) && ts.isAssignmentOperator(n.operatorToken.kind))
                trees.push(operand(n));
            if (projection === "jump") {
                if (ts.isBreakStatement(n) || ts.isContinueStatement(n)) {
                    trees.push([ts.SyntaxKind[n.kind], n.label?.text ?? null]);
                } else if (ts.isLabeledStatement(n)) {
                    trees.push(["LabeledStatement", n.label.text, statementShape(n.statement)]);
                } else if (ts.isSwitchStatement(n)) {
                    trees.push(["SwitchStatement", n.caseBlock.clauses.map(c => [ts.isDefaultClause(c), c.statements.length])]);
                }
            }
            if (projection === "private name") {
                const record = privateShape(n);
                if (record) trees.push(record);
            }
            if (projection === "type predicate" && ts.isTypePredicateNode(n)) trees.push(type(n));
            if (projection === "JSDoc type" && ts.SyntaxKind[n.kind].startsWith("JSDoc") && ts.SyntaxKind[n.kind].endsWith("Type"))
                trees.push(type(n));
            if (projection === "function type" && ts.isFunctionTypeNode(n)) trees.push(type(n));
            if (projection === "marked property" && n.parent && ts.isObjectLiteralExpression(n.parent)
                    && (n.questionToken || n.exclamationToken)) {
                let payload;
                if (ts.isMethodDeclaration(n)) {
                    payload = ["method", (n.modifiers || []).some(m => m.kind === ts.SyntaxKind.AsyncKeyword),
                        !!n.asteriskToken, signature(n)];
                } else if (ts.isShorthandPropertyAssignment(n)) {
                    payload = ["shorthand", n.objectAssignmentInitializer ? key(n.objectAssignmentInitializer) : null];
                } else {
                    payload = ["assignment", key(n.initializer)];
                }
                trees.push([key(n.name), !!n.questionToken, !!n.exclamationToken, payload]);
            }
            if (projection === "arrow signature" && ts.isArrowFunction(n)) {
                const async = (n.modifiers || []).some(m => m.kind === ts.SyntaxKind.AsyncKeyword);
                trees.push([async, !ts.isBlock(n.body), ...signature(n)]);
            }
            if (projection === "alias" && ts.isTypeAliasDeclaration(n)) trees.push([n.name.text, params(n), type(n.type)]);
            const children = [];
            ts.forEachChild(n, child => { children.push(child); });
            for (let i = children.length - 1; i >= 0; i--) pending.push(children[i]);
        }
    } catch (e) { return {unmapped: e.message}; }
    if (projection === "heritage source") return {trees, statementSpans: f.statements.map(n => [n.getStart(f), n.end])};
    return {trees};
})));
