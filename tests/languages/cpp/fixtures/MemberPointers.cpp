namespace demo {
    struct Cell {
        int value;
        int read(int extra) const { return value + extra; }
    };
}
using Data = int demo::Cell::*;
using Getter = int (demo::Cell::*)(int) const;
int demo::Cell::* const field = &demo::Cell::value;
int (demo::Cell::*method)(int) const = &demo::Cell::read;
int read(demo::Cell& c, demo::Cell* p) {
    return c.*field + 2 * (p->*method)(1);
}
int first(1), *ptr = &first, numbers[2] = {1, 2};
int next(int), (*callback)(int) = next;
int grouped() {
    int a = 1, b(a + 1);
    for (int i = 0, j = 2; i < j; ++i) b += numbers[i];
    return b;
}
