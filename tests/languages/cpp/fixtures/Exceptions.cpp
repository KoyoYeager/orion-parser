using Outer = int;

int dispatch(int value) try {
    return value ? value : throw value + 1;
} catch (const int &Outer) {
    return sizeof(Outer);
} catch (Outer *) {
    return sizeof(Outer);
} catch (...) {
    throw;
}

int nested(int x) {
    try {
        try { throw x = 3; }
        catch (int *) { throw; }
    } catch (Outer) {
        return sizeof(Outer);
    }
    return 0;
}

struct Sample {
    int value;
    Sample(int input);
    ~Sample() try {} catch (...) {}
};
Sample::Sample(int input) try : value(input) {
    if (input < 0) throw input;
} catch (int) {
    throw;
}
