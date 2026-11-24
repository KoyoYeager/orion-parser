namespace left {
    using Row = int[4];
    using Matrix = Row[2];
    using RowPtr = Row *;
    using Pointers = int *[4];
    using Slots = const Pointers;
}
namespace right {
    typedef signed int Row[4];
    using Matrix = int[2][4];
    using RowPtr = int (*)[4];
    using Slots = int *const[4];
}
namespace view { using namespace left; using namespace right; }
int cell(view::Matrix &m) { return m[1][2]; }
view::RowPtr borrow(view::Row &r) { return &r; }
int read(view::Slots &s) { return *s[0]; }
