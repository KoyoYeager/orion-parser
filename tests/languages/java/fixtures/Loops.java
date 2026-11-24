package fixtures;

@Checks(value = {@Kind("loop"), @Kind("label")}, target = int[].class)
class Loops {
    int walk(int[] values) {
        int sum = 0;
        outer: for (int i = 0, j = 0; i < values.length; i++, j += 2) {
            if (values[i] < 0) continue outer;
            synchronized (this) {
                sum += values[i];
            }
        }
        do { sum--; } while (sum > 10);
        assert sum <= 10 : "limit";
        for (;;) break;
        return sum;
    }
}
