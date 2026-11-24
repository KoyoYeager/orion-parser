auto identity = [](auto value){ return value; };
using F = decltype(identity);
int braced() { return F{}.operator()<int>(1); }
int parens() { return F().operator()<int>(2); }
int copied(F f) { return F(f).operator()<int>(3); }
int ref(F f) { return static_cast<F &>(f).operator()<int>(4); }
int ptr(const F *p) { return const_cast<F *>(p)->operator()<int>(5); }
int cstyle(F f) { return ((F &)f).operator()<int>(6); }
