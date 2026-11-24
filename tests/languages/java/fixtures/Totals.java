package fixtures;

class Totals {
    private final int bias;

    Totals(int bias) {
        this.bias = bias;
    }

    int sumPositive(int[] values) {
        int sum = 0;
        for (int value : values) {
            if (value > 0) sum += value * 2 + bias;
        }
        return sum;
    }

    static int run(int[] data) {
        return new Totals(1).sumPositive(data);
    }
}
