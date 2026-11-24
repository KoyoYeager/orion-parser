package fixtures;

@interface Options {
    int LIMIT = 2;
    String[] tags() default {"a", "b"};
    @Deprecated public abstract Class<?> owner() default Options.class;
    int levels()[] default {1, 2};
    enum Flag { ON, OFF }
    @interface Nested { String value(); }
    interface Service {}
    class Holder {}
    ;
}

enum Palette {
    @Deprecated RED(1) { int code() { return 7; } },
    BLUE(2),
    ;
    private final int number;
    Palette(int number) { this.number = number; }
    int code() { return number; }
    String description() {
        return """\u0009
                one\s
                  two\
                three \101
                """;
    }
}
