auto identity = [](auto x){return x;};
using F = decltype(identity);
int same(bool b, F &x, F &y) { return (b ? x : y).operator()<int>(1); }
int null_left(bool b, F *p) { return (b ? nullptr : p)->operator()<int>(2); }
int zero_right(bool b, F *p) { return (b ? p : 0x0'0ULL)->operator()<int>(3); }
int throws(bool b, F &x) { return (b ? (throw 1) : x).operator()<int>(4); }
int decay(bool b, F (&a)[2], F *p) { return (b ? a : p)->operator()<int>(5); }
template<class T> int dependent(T test, F &x) { return (test ? x : x).template operator()<int>(6); }
struct Consumer { template<class T> int get(); };
int nested(bool b, bool c, Consumer *p) { return (b ? (c ? nullptr : nullptr) : p)->get<int>(); }
struct Intermediate : Consumer {};
struct Derived : Intermediate {};
int inherited(bool b, Derived &d, Consumer &c) { return (b ? d : c).get<long>(); }
int inherited_ptr(bool b, Consumer *p, Derived *q) { return (b ? p : q)->get<int>(); }
