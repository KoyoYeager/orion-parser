namespace sample {
    template<class T, unsigned N>
    struct Array {
        T items[N];
        constexpr T first() const noexcept { return items[0]; }
    };

    template<typename T>
    constexpr T twice(T value) { return value + value; }

    using Index = unsigned;
    constexpr int sum(const int* values, Index n) {
        int result = 0;
        for (Index i = 0; i < n; ++i) {
            if (values[i] > 0) result += twice<int>(values[i]);
        }
        return result;
    }
    constexpr int run() {
        Array<int, 3> values{{1, -1, 3}};
        return sum(values.items, 3);
    }
}
static_assert(sample::run() == 8);
