int sum_positive(const int *values, int length) {
    int sum = 0;
    for (int i = 0; i < length; ++i) {
        if (values[i] > 0)
            sum += values[i] * 2 + 1;
    }
    return sum;
}

int main(void) {
    int values[3] = {1, -2, 3};
    int length = 3;
    while (length > 2) length = length - 1;
    return sum_positive(values, length);
}
