package fixtures;

class AnnotatedReferences {
    java.util.function.Function<String, String> trim = @A String::trim;
    java.util.function.IntFunction<int[]> allocate = @A int @B []::new;
    java.util.function.Supplier<String> create = @A String::new;
}
