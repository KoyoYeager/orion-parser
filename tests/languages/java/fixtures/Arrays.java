package fixtures;

class Arrays {
    String[][] names = {{"one"}, {}, {"two", "three"},};
    int[][] sized(int n) { return new int[n + 1][]; }
    Object first() { return new String[]{"first", "second"}[0]; }
    class Inner { <T> Inner(T value) {} }

    Object build(Arrays outer) {
        Inner first = outer.new <String> Inner("one");
        return new Inner(first) { int count(){return 1;} };
    }
    String[][] labels(int n) { return new String @Dim [n][]; }
    int[][][] deep() { return new int[1][2][]; }
    int[][] initialized() { return new int[][]{{1}, {}}; }
    Inner qualified() { return (this).new Inner(null); }

    @java.lang.annotation.Target(java.lang.annotation.ElementType.TYPE_USE)
    @interface Dim {}
}
