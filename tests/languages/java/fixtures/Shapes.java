package fixtures;

sealed interface Shape permits Shapes, Point {}
abstract sealed class Shapes implements Shape permits MoreShapes {}
non-sealed class MoreShapes extends Shapes {}
record Point<T>(@Deprecated T x, int... samples) implements Shape {
    public Point {
        if (x == null) throw new IllegalArgumentException();
    }
    public int count() { return samples.length; }
    record Empty() {}
    static { int permits = 1; }
}

record Pair(Point<String> point, int count) {}
class Queries {
    boolean matches(Object obj) {
        return obj instanceof Pair(Point(var x, int[] samples), int n) && n > 0;
    }
    boolean plain(Object o) { return o instanceof String; }
    int local(int record) {
        @Deprecated record Holder(int x) {}
        return new Holder(record).x();
    }
}
