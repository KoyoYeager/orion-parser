import com.sun.tools.javac.parser.ScannerFactory;
import com.sun.tools.javac.parser.Tokens.TokenKind;
import com.sun.tools.javac.util.Context;
import com.sun.tools.javac.util.Log;
import java.net.URI;
import javax.tools.DiagnosticCollector;
import javax.tools.DiagnosticListener;
import javax.tools.JavaFileObject;
import javax.tools.SimpleJavaFileObject;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.List;

/** Lexical reference for exactly the JDK used by the syntax oracle. */
class JavaLexOracle {
    private static void characterClasses() {
        int previous = -1;
        for (int cp = 0; cp <= Character.MAX_CODE_POINT; cp++) {
            int kind = Character.isJavaIdentifierStart(cp) ? 3 : Character.isIdentifierIgnorable(cp) ? 2 :
                       Character.isJavaIdentifierPart(cp) ? 1 : 0;
            if (kind != previous) {
                System.out.printf("%X %d%n", cp, kind);
                previous = kind;
            }
        }
    }

    public static void main(String[] args) throws Exception {
        var version = Runtime.version();
        if (!version.version().equals(List.of(21, 0, 2)) || version.build().orElse(-1) != 13)
            throw new IllegalStateException("Expected OpenJDK 21.0.2+13");
        if (args.length == 1 && args[0].equals("characters")) {
            characterClasses();
            return;
        }
        boolean errors = args.length == 1 && args[0].equals("errors");
        var reader = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.US_ASCII));
        for (String line; (line = reader.readLine()) != null;) {
            var source = new String(Base64.getDecoder().decode(line), StandardCharsets.UTF_8);
            var context = new Context();
            var diagnostics = new DiagnosticCollector<JavaFileObject>();
            context.put(DiagnosticListener.class, diagnostics);
            Log.instance(context).useSource(new SimpleJavaFileObject(URI.create("mem:///Lex.java"), JavaFileObject.Kind.SOURCE) {
                @Override public CharSequence getCharContent(boolean ignoreEncodingErrors) { return source; }
            });
            var scanner = ScannerFactory.instance(context).newScanner(source, false);
            var fields = new java.util.StringJoiner(" ");
            for (scanner.nextToken(); scanner.token().kind != TokenKind.EOF; scanner.nextToken()) {
                var token = scanner.token();
                fields.add(token.kind.name() + ":" + token.pos + ":" + token.endPos);
            }
            var messages = new java.util.StringJoiner(" ");
            for (var diagnostic : diagnostics.getDiagnostics())
                messages.add(diagnostic.getCode() + ":" + diagnostic.getPosition());
            if (!errors && messages.length() != 0) throw new IllegalStateException(messages.toString());
            System.out.println(errors ? messages : fields);
        }
    }
}
