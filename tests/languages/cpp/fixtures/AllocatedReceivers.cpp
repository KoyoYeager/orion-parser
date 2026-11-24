auto identity = [](auto x){return x;};
using F = decltype(identity);
using Row = F[3];
using Ptr = F *;
int scalar() { return (new F)->operator()<int>(1); }
int array() { return (new F[2])[0].operator()<int>(2); }
int matrix() { return (new F[2][3])[1][2].operator()<long>(3); }
int named_row() { return (new Row)[0].operator()<int>(4); }
int named_pointer(F *p) { return (*(new Ptr(p)))->operator()<int>(5); }
int parenthesized() { return (new (F[2]))[1].operator()<int>(6); }
struct Box { template<class T> int read(); };
int record() { return (new Box[2])[1].read<int>(); }
int aliases() {
    using NextRow = Row;
    return (new NextRow[2])[0][1].operator()<int>(7);
}
namespace model { using Values = Row; }
int qualified() { return (new (model::Values))[0].operator()<int>(8); }
