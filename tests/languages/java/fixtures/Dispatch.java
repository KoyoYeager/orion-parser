package fixtures;

class Dispatch {
    record Pair(int x, int y) {}
    int score(Object obj, boolean enabled) {
        return switch (obj) {
            case Pair(int x, int y) when enabled && x > 0 -> x + y;
            case Pair(var x, var y) -> { yield y; }
            case String s when (enabled) -> s.length();
            case null, default -> throw new IllegalArgumentException();
        };
    }
    int legacy(int n) {
        switch (n) {
            case 1:
            case 2: n++; break;
            default: n = 0;
        }
        return switch (n) { case 0, 1 -> n; default -> -1; };
    }
}
