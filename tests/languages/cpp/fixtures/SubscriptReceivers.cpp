auto identity = [](auto x){return x;};
using F = decltype(identity);
int at(F *items) { return items[0].operator()<int>(7); }
int matrix(F (&rows)[2][3]) { return rows[1][2].operator()<int>(8); }
using Row = F[3];
int alias_row(Row &r) { return r[0].operator()<long>(9); }
int swapped(F *p) { return 1[p].operator()<int>(10); }
int local() { F items[2]; return items[1].operator()<int>(11); }
struct Cell { template<class T> int read(); };
int cells(Cell (*rows)[2]) { return rows[0][1].read<int>(); }
using Cells = Cell[3];
int named_array(Cells &r) { return r[0].read<long>(); }
struct Store { F &operator[](unsigned) { return identity; } };
int fetched(Store &s) { return s[1].operator()<int>(12); }
struct Grid { Store &operator[](int); };
int chained(Grid &g) { return g[0][1].operator()<int>(13); }
struct Entry { template<class T> int read(); } entries[2];
int entry() { return entries[0].read<int>(); }
using Table = struct InlineRow { template<class T> int read(); }[2];
int inline_record(Table &t) { return t[0].read<int>(); }
typedef struct Indexed { template<class T> int read(); } IndexedArray[2];
int from_typedef(IndexedArray &v) { return v[1].read<int>(); }
