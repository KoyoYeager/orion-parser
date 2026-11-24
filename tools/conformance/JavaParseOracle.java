import com.sun.source.tree.ClassTree;
import com.sun.source.tree.AssignmentTree;
import com.sun.source.tree.CompoundAssignmentTree;
import com.sun.source.tree.BinaryTree;
import com.sun.source.tree.UnaryTree;
import com.sun.source.tree.ConditionalExpressionTree;
import com.sun.source.tree.ParenthesizedTree;
import com.sun.source.tree.ArrayAccessTree;
import com.sun.source.tree.ReturnTree;
import com.sun.source.tree.TypeCastTree;
import com.sun.source.tree.NewArrayTree;
import com.sun.source.tree.TryTree;
import com.sun.source.tree.CaseTree;
import com.sun.source.tree.ConstantCaseLabelTree;
import com.sun.source.tree.PatternCaseLabelTree;
import com.sun.source.tree.DefaultCaseLabelTree;
import com.sun.source.tree.SwitchExpressionTree;
import com.sun.source.tree.SwitchTree;
import com.sun.source.tree.ExpressionStatementTree;
import com.sun.source.tree.LiteralTree;
import com.sun.source.tree.IdentifierTree;
import com.sun.source.tree.PatternTree;
import com.sun.source.tree.BindingPatternTree;
import com.sun.source.tree.DeconstructionPatternTree;
import com.sun.source.tree.InstanceOfTree;
import com.sun.source.tree.LambdaExpressionTree;
import com.sun.source.tree.MemberReferenceTree;
import com.sun.source.tree.MethodInvocationTree;
import com.sun.source.tree.MemberSelectTree;
import com.sun.source.util.TreeScanner;
import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.tree.Tree;
import com.sun.source.tree.DirectiveTree;
import com.sun.source.tree.MethodTree;
import com.sun.source.tree.VariableTree;
import com.sun.source.tree.ExportsTree;
import com.sun.source.tree.OpensTree;
import com.sun.source.tree.ModuleTree;
import com.sun.source.tree.ProvidesTree;
import com.sun.source.tree.RequiresTree;
import com.sun.source.tree.UsesTree;
import com.sun.source.util.JavacTask;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.StringJoiner;
import javax.tools.Diagnostic;
import javax.tools.DiagnosticCollector;
import javax.tools.JavaCompiler;
import javax.tools.JavaFileObject;
import javax.tools.ToolProvider;

/** Syntax-only reference for Java SE 21. Each input file is parsed independently. */
class JavaParseOracle {
    private static String quoted(String s) {
        var text = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '"' || c == '\\') text.append('\\').append(c);
            else if (c < ' ' || Character.isSurrogate(c))
                text.append(String.format(Locale.ROOT, "\\u%04x", (int) c));
            else text.append(c);
        }
        return text.append('"').toString();
    }

    private static String names(List<? extends Tree> elements) {
        var result = new StringJoiner(",", "[", "]");
        if (elements != null) {
            for (Tree element : elements) result.add(quoted(element.toString()));
        }
        return result.toString();
    }

    private static String directive(DirectiveTree tree) {
        return switch (tree) {
            case RequiresTree r -> "[" + quoted("Requires") + "," + quoted(r.getModuleName().toString())
                    + "," + r.isStatic() + "," + r.isTransitive() + "]";
            case ExportsTree e -> "[" + quoted("Exports") + "," + quoted(e.getPackageName().toString())
                    + "," + names(e.getModuleNames()) + "]";
            case OpensTree o -> "[" + quoted("Opens") + "," + quoted(o.getPackageName().toString())
                    + "," + names(o.getModuleNames()) + "]";
            case UsesTree u -> "[" + quoted("Uses") + "," + quoted(u.getServiceName().toString()) + "]";
            case ProvidesTree p -> "[" + quoted("Provides") + "," + quoted(p.getServiceName().toString())
                    + "," + names(p.getImplementationNames()) + "]";
            default -> throw new IllegalArgumentException("Unexpected directive " + tree.getKind());
        };
    }

    private static String selectionName(Tree tree) {
        if (tree instanceof IdentifierTree id) return id.getName().toString();
        if (tree instanceof MemberSelectTree m) {
            String base = selectionName(m.getExpression());
            if (base != null) return base + "." + m.getIdentifier();
        }
        return null;
    }

    private static void functionalShapes(CompilationUnitTree unit, StringJoiner result, StringJoiner invocations) {
        new TreeScanner<Void, Void>() {
            @Override public Void visitMethodInvocation(MethodInvocationTree call, Void unused) {
                Tree select = call.getMethodSelect();
                Tree qualifier = null;
                String name = select.toString();
                if (select instanceof MemberSelectTree member) {
                    name = member.getIdentifier().toString();
                    qualifier = member.getExpression();
                }
                if (name.equals("this") || name.equals("super") || !call.getTypeArguments().isEmpty()) {
                    String qname = selectionName(qualifier);
                    invocations.add("[" + quoted(name) + "," + (qualifier == null ? "null" : quoted(qualifier.getKind().name()))
                            + "," + (qname == null ? "null" : quoted(qname)) + "," + names(call.getTypeArguments())
                            + "," + call.getArguments().size() + "]");
                }
                return super.visitMethodInvocation(call, unused);
            }
            @Override public Void visitLambdaExpression(LambdaExpressionTree lambda, Void unused) {
                var params = new StringJoiner(",", "[", "]");
                for (var p : lambda.getParameters()) {
                    params.add("[" + quoted(p.getName().toString()) + ","
                            + (p.getType() == null ? "null" : quoted(p.getType().toString())) + "]");
                }
                var calls = new StringJoiner(",", "[", "]");
                new TreeScanner<Void, Void>() {
                    @Override public Void visitMethodInvocation(MethodInvocationTree call, Void context) {
                        var select = call.getMethodSelect();
                        calls.add(quoted(select instanceof MemberSelectTree m
                                ? m.getIdentifier().toString() : select.toString()));
                        return super.visitMethodInvocation(call, context);
                    }
                }.scan(lambda.getBody(), null);
                result.add("[" + quoted("lambda") + "," + params + ","
                        + quoted(lambda.getBody().getKind().name()) + "," + calls + "]");
                return super.visitLambdaExpression(lambda, unused);
            }

            @Override public Void visitMemberReference(MemberReferenceTree ref, Void unused) {
                String name = ref.getMode() == MemberReferenceTree.ReferenceMode.NEW ? "new" : ref.getName().toString();
                result.add("[" + quoted("reference") + "," + quoted(name) + "," + names(ref.getTypeArguments()) + "]");
                return super.visitMemberReference(ref, unused);
            }
        }.scan(unit, null);
    }

    private static String patternShape(PatternTree pattern) {
        if (pattern instanceof BindingPatternTree binding) {
            var variable = binding.getVariable();
            var type = variable.getType() == null ? "var" : variable.getType().toString();
            return "[" + quoted("binding") + "," + quoted(type) + "," + quoted(variable.getName().toString()) + "]";
        }
        if (pattern instanceof DeconstructionPatternTree record) {
            var components = new StringJoiner(",", "[", "]");
            for (var nested : record.getNestedPatterns()) components.add(patternShape(nested));
            return "[" + quoted("record") + "," + quoted(record.getDeconstructor().toString()) + "," + components + "]";
        }
        return quoted(pattern.getKind().name());
    }

    private static void instanceTests(CompilationUnitTree unit, StringJoiner result) {
        new TreeScanner<Void, Void>() {
            @Override public Void visitInstanceOf(InstanceOfTree test, Void unused) {
                result.add(test.getPattern() == null ? quoted(test.getType().toString()) : patternShape(test.getPattern()));
                return super.visitInstanceOf(test, unused);
            }
        }.scan(unit, null);
    }

    private static String caseShape(CaseTree arm) {
        var labels = new StringJoiner(",", "[", "]");
        for (var label : arm.getLabels()) {
            if (label instanceof PatternCaseLabelTree p) labels.add(patternShape(p.getPattern()));
            else if (label instanceof DefaultCaseLabelTree) labels.add(quoted("default"));
            else if (label instanceof ConstantCaseLabelTree c) {
                Tree value = c.getConstantExpression();
                if (value instanceof IdentifierTree || value instanceof MemberSelectTree)
                    labels.add(quoted(value.toString()));
                else labels.add(quoted(value instanceof LiteralTree ? "literal:" + value.toString() : value.getKind().name()));
            }
        }
        var statements = new StringJoiner(",", "[", "]");
        if (arm.getStatements() != null)
            for (var stmt : arm.getStatements()) statements.add(quoted(stmt.getKind().name()));
        Tree body = arm.getBody();
        if (body instanceof ExpressionStatementTree e) body = e.getExpression();
        return "[" + labels + "," + (arm.getGuard() != null) + "," + statements + ","
                + (body == null ? "null" : quoted(body.getKind().name())) + "]";
    }

    private static void switchShapes(CompilationUnitTree unit, StringJoiner result) {
        new TreeScanner<Void, Void>() {
            private void record(Tree tree, List<? extends CaseTree> cases) {
                var arms = new StringJoiner(",", "[", "]");
                for (var arm : cases) arms.add(caseShape(arm));
                result.add("[" + quoted(tree.getKind().name()) + "," + arms + "]");
            }
            @Override public Void visitSwitch(SwitchTree tree, Void unused) {
                record(tree, tree.getCases());
                return super.visitSwitch(tree, unused);
            }
            @Override public Void visitSwitchExpression(SwitchExpressionTree tree, Void unused) {
                record(tree, tree.getCases());
                return super.visitSwitchExpression(tree, unused);
            }
        }.scan(unit, null);
    }

    private static void resourceAndArrayShapes(CompilationUnitTree unit, StringJoiner tries, StringJoiner arrays) {
        new TreeScanner<Void, Void>() {
            @Override public Void visitTry(TryTree tree, Void unused) {
                var resources = new StringJoiner(",", "[", "]");
                for (Tree r : tree.getResources()) {
                    if (r instanceof VariableTree v) {
                        resources.add("[" + quoted("variable") + "," + quoted(v.getName().toString()) + ","
                                + quoted(v.getType() == null ? "var" : v.getType().toString()) + "]");
                    } else {
                        resources.add("[" + quoted("access") + "," + quoted(r.getKind().name()) + "]");
                    }
                }
                var catches = new StringJoiner(",", "[", "]");
                for (var clause : tree.getCatches()) {
                    var p = clause.getParameter();
                    catches.add("[" + quoted(p.getName().toString()) + "," + quoted(p.getType() == null ? "var" : p.getType().toString()) + "]");
                }
                tries.add("[" + resources + "," + catches + "," + (tree.getFinallyBlock() != null) + "]");
                return super.visitTry(tree, unused);
            }
            @Override public Void visitNewArray(NewArrayTree tree, Void unused) {
                var dimensions = new StringJoiner(",", "[", "]");
                for (var dimension : tree.getDimensions()) dimensions.add(quoted(dimension.getKind().name()));
                Tree element = tree.getType();
                int trailing = 0;
                while (element instanceof com.sun.source.tree.ArrayTypeTree || (element instanceof com.sun.source.tree.AnnotatedTypeTree t && t.getUnderlyingType() instanceof com.sun.source.tree.ArrayTypeTree)) {
                    if (element instanceof com.sun.source.tree.ArrayTypeTree a) {
                        trailing++;
                        element = a.getType();
                    } else {
                        element = ((com.sun.source.tree.AnnotatedTypeTree) element).getUnderlyingType();
                    }
                }
                arrays.add("[" + (element == null ? "null" : quoted(element.toString())) + "," + trailing
                        + "," + dimensions + "," + (tree.getInitializers() == null ? "null" : tree.getInitializers().size()) + "]");
                return super.visitNewArray(tree, unused);
            }
        }.scan(unit, null);
    }

    private static void textBlocks(JavacTask task, CompilationUnitTree unit, StringJoiner result) throws Exception {
        var positions = com.sun.source.util.Trees.instance(task).getSourcePositions();
        var source = unit.getSourceFile().getCharContent(true).toString();
        new TreeScanner<Void, Void>() {
            @Override public Void visitLiteral(LiteralTree literal, Void unused) {
                long start = positions.getStartPosition(unit, literal);
                if (start >= 0 && literal.getValue() instanceof String value && source.startsWith("\"\"\"", (int) start))
                    result.add(quoted(value));
                return super.visitLiteral(literal, unused);
            }
        }.scan(unit, null);
    }

    private static String memberList(ClassTree type) {
        var members = new StringJoiner(",", "[", "]");
        for (Tree member : type.getMembers()) {
            if (type.getKind() == Tree.Kind.ENUM && member instanceof VariableTree constant
                    && constant.getInitializer() instanceof com.sun.source.tree.NewClassTree value
                    && constant.getType().toString().equals(type.getSimpleName().toString())
                    && value.getIdentifier().toString().equals(type.getSimpleName().toString())) {
                var annotations = new StringJoiner(",", "[", "]");
                for (var a : constant.getModifiers().getAnnotations()) annotations.add(quoted(a.getAnnotationType().toString()));
                members.add("[" + quoted("constant") + "," + quoted(constant.getName().toString()) + ","
                        + annotations + "," + value.getArguments().size() + ","
                        + (value.getClassBody() == null ? "null" : memberList(value.getClassBody())) + "]");
            } else if (member instanceof VariableTree f) {
                members.add("[" + quoted("field") + "," + quoted(f.getName().toString())
                        + "," + quoted(f.getType() == null ? "var" : f.getType().toString()) + "]");
            } else if (type.getKind() == Tree.Kind.ANNOTATION_TYPE && member instanceof MethodTree element) {
                members.add("[" + quoted("element") + "," + quoted(element.getName().toString()) + ","
                        + quoted(element.getReturnType().toString()) + ","
                        + (element.getDefaultValue() == null ? "null" : quoted(element.getDefaultValue().getKind().name())) + "]");
            } else if (member instanceof MethodTree m) {
                var parameters = new StringJoiner(",", "[", "]");
                for (var p : m.getParameters()) {
                    parameters.add("[" + quoted(p.getName().toString()) + "," + quoted(p.getType() == null ? "var" : p.getType().toString()) + "]");
                }
                String body = "null";
                if (m.getBody() != null) {
                    var statements = new StringJoiner(",", "[", "]");
                    for (var stmt : m.getBody().getStatements()) statements.add(quoted(stmt.getKind().name()));
                    body = statements.toString();
                }
                var methodAnnotations = new StringJoiner(",", "[", "]");
                for (var a : m.getModifiers().getAnnotations()) methodAnnotations.add(quoted(a.getAnnotationType().toString()));
                String receiver = "null";
                if (m.getReceiverParameter() != null) {
                    var r = m.getReceiverParameter();
                    var annotations = new StringJoiner(",", "[", "]");
                    for (var a : r.getModifiers().getAnnotations()) annotations.add(quoted(a.getAnnotationType().toString()));
                    receiver = "[" + quoted(r.getNameExpression().toString()) + "," + quoted(r.getType().toString())
                            + "," + annotations + "]";
                }
                members.add("[" + quoted(m.getName().toString()) + ","
                        + (m.getReturnType() == null ? "null" : quoted(m.getReturnType().toString()))
                        + "," + parameters + "," + names(m.getThrows()) + "," + body + "," + names(m.getTypeParameters()) + "," + receiver + "," + methodAnnotations + "]");
            } else if (member instanceof com.sun.source.tree.BlockTree b) {
                members.add("[\"BLOCK\"," + b.isStatic() + "]");
            } else if (member instanceof ClassTree nested) {
                members.add(memberShape(nested));
            } else {
                members.add("[" + quoted(member.getKind().name()) + "]");
            }
        }
        return members.toString();
    }

    private static String memberShape(ClassTree type) {
        return "[" + quoted(type.getKind().name()) + "," + quoted(type.getSimpleName().toString())
                + "," + (type.getExtendsClause() == null ? "null" : quoted(type.getExtendsClause().toString()))
                + "," + names(type.getImplementsClause()) + "," + memberList(type) + "," + names(type.getTypeParameters()) + "," + names(type.getPermitsClause())
                + "," + type.getModifiers().getFlags().contains(javax.lang.model.element.Modifier.SEALED)
                + "," + type.getModifiers().getFlags().contains(javax.lang.model.element.Modifier.NON_SEALED) + "]";
    }

    private static String expressionShape(Tree tree) {
        var parts = new StringJoiner(",", "[", "]");
        parts.add(quoted(tree.getKind().name()));
        switch (tree) {
            case BinaryTree b -> { parts.add(expressionShape(b.getLeftOperand())); parts.add(expressionShape(b.getRightOperand())); }
            case AssignmentTree a -> { parts.add(expressionShape(a.getVariable())); parts.add(expressionShape(a.getExpression())); }
            case CompoundAssignmentTree a -> { parts.add(expressionShape(a.getVariable())); parts.add(expressionShape(a.getExpression())); }
            case UnaryTree u -> parts.add(expressionShape(u.getExpression()));
            case ConditionalExpressionTree c -> {
                parts.add(expressionShape(c.getCondition())); parts.add(expressionShape(c.getTrueExpression()));
                parts.add(expressionShape(c.getFalseExpression()));
            }
            case ParenthesizedTree p -> parts.add(expressionShape(p.getExpression()));
            case ArrayAccessTree a -> { parts.add(expressionShape(a.getExpression())); parts.add(expressionShape(a.getIndex())); }
            case TypeCastTree c -> { parts.add(quoted(c.getType().toString())); parts.add(expressionShape(c.getExpression())); }
            case InstanceOfTree t -> { parts.add(expressionShape(t.getExpression())); parts.add(quoted(t.getType().toString())); }
            case MemberSelectTree m -> { parts.add(expressionShape(m.getExpression())); parts.add(quoted(m.getIdentifier().toString())); }
            case IdentifierTree id -> parts.add(quoted(id.getName().toString()));
            case LiteralTree literal -> parts.add(quoted(literal.toString()));
            case LambdaExpressionTree l -> {
                var parameters = new StringJoiner(",", "[", "]");
                for (var param : l.getParameters()) parameters.add(quoted(param.getName().toString()));
                parts.add(parameters.toString()); parts.add(expressionShape(l.getBody()));
            }
            default -> throw new IllegalArgumentException("Unsupported matrix expression " + tree.getKind());
        }
        return parts.toString();
    }

    private static String parse(JavaCompiler compiler, Path path, String mode) throws Exception {
        var diagnostics = new DiagnosticCollector<JavaFileObject>();
        try (var manager = compiler.getStandardFileManager(diagnostics, Locale.ROOT, StandardCharsets.UTF_8)) {
            var files = manager.getJavaFileObjectsFromPaths(List.of(path));
            var task = (JavacTask) compiler.getTask(null, manager, diagnostics,
                    List.of("--release", "21", "-proc:none"), null, files);
            String module = "null", packageName = "null";
            boolean open = false;
            var imports = new StringJoiner(",", "[", "]");
            var annotations = new StringJoiner(",", "[", "]");
            var expressions = new StringJoiner(",", "[", "]");
            var directives = new StringJoiner(",", "[", "]");
            var tries = new StringJoiner(",", "[", "]");
            var arrays = new StringJoiner(",", "[", "]");
            var blocks = new StringJoiner(",", "[", "]");
            var switches = new StringJoiner(",", "[", "]");
            var instances = new StringJoiner(",", "[", "]");
            var invocations = new StringJoiner(",", "[", "]");
            var functional = new StringJoiner(",", "[", "]");
            var shapes = new StringJoiner(",", "[", "]");
            var types = new StringJoiner(",", "[", "]");
            for (CompilationUnitTree unit : task.parse()) {
                boolean detailed = mode.isEmpty() && diagnostics.getDiagnostics().stream().noneMatch(d -> d.getKind() == Diagnostic.Kind.ERROR);
                if (detailed) {
                    functionalShapes(unit, functional, invocations);
                    instanceTests(unit, instances);
                    switchShapes(unit, switches);
                    textBlocks(task, unit, blocks);
                    resourceAndArrayShapes(unit, tries, arrays);
                }
                if (unit.getPackageName() != null) packageName = quoted(unit.getPackageName().toString());
                for (var item : unit.getImports()) {
                    imports.add("[" + item.isStatic() + "," + quoted(item.getQualifiedIdentifier().toString()) + "]");
                }
                if (unit.getModule() != null) {
                    var declaration = unit.getModule();
                    module = quoted(declaration.getName().toString());
                    open = declaration.getModuleType() == ModuleTree.ModuleKind.OPEN;
                    for (var a : declaration.getAnnotations()) annotations.add(quoted(a.getAnnotationType().toString()));
                    for (var d : declaration.getDirectives()) directives.add(directive(d));
                }
                for (Tree decl : unit.getTypeDecls()) {
                    if (detailed && decl instanceof ClassTree c) shapes.add(memberShape(c));
                    if (mode.equals("--expressions") && decl instanceof ClassTree c) {
                        for (var member : c.getMembers()) {
                            var method = (MethodTree)member;
                            var returned = (ReturnTree)method.getBody().getStatements().get(0);
                            expressions.add("[" + quoted(method.getName().toString()) + "," + expressionShape(returned.getExpression()) + "]");
                        }
                    }
                    String name = decl instanceof ClassTree c ? quoted(c.getSimpleName().toString()) : "null";
                    types.add("{\"kind\":" + quoted(decl.getKind().name()) + ",\"name\":" + name + "}");
                }
            }
            var errors = new ArrayList<String>();
            for (var d : diagnostics.getDiagnostics()) {
                if (d.getKind() == Diagnostic.Kind.ERROR) {
                    errors.add("{\"code\":" + quoted(d.getCode()) + ",\"line\":" + d.getLineNumber()
                            + ",\"column\":" + d.getColumnNumber() + "}");
                }
            }
            return "{\"file\":" + quoted(path.toString()) + ",\"accepted\":" + errors.isEmpty()
                    + ",\"package\":" + packageName + ",\"module\":" + module
                    + ",\"open\":" + open + ",\"imports\":" + imports + ",\"annotations\":" + annotations
                    + ",\"expressions\":" + expressions + ",\"directives\":" + directives + ",\"tries\":" + tries + ",\"arrays\":" + arrays + ",\"textBlocks\":" + blocks + ",\"switches\":" + switches + ",\"instances\":" + instances + ",\"invocations\":" + invocations + ",\"functional\":" + functional + ",\"shapes\":" + shapes + ",\"types\":" + types + ",\"errors\":[" + String.join(",", errors) + "]}";
        }
    }

    public static void main(String[] args) throws Exception {
        var version = Runtime.version();
        if (!version.version().equals(List.of(21, 0, 2)) || version.build().orElse(-1) != 13) {
            throw new IllegalStateException("Expected OpenJDK 21.0.2+13, found " + version);
        }
        if (args.length == 0) throw new IllegalArgumentException("Pass at least one Java source path");
        var compiler = ToolProvider.getSystemJavaCompiler();
        String mode = args[0].startsWith("--") ? args[0] : "";
        for (int i = mode.isEmpty() ? 0 : 1; i < args.length; i++)
            System.out.println(parse(compiler, Path.of(args[i]), mode));
    }
}
