auto identity=[](auto x){return x;};
using F=decltype(identity);
int item(F *p) { return (p + 1)->operator()<int>(2); }
int swapped(F *p) { return (1 + p)->operator()<int>(3); }
int minus(F *p, int n) { return (p - n)->operator()<long>(4); }
int matrix(F (&a)[2][3]) { return (*(a + 1))[0].operator()<int>(5); }
struct Offset { F &operator+(int){return identity;} };
int member(Offset o) { return (o + 2).operator()<int>(6); }
namespace lib { struct Back {}; F *operator-(Back, int){return &identity;} }
int other(lib::Back b) { return (b - 2)->operator()<int>(7); }
int distance(F *p, F *q) { return (p + (q - p))->operator()<int>(8); }
