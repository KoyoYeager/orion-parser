struct Apply { template<class T> T operator()(T value) const { return value; } };
int invoke(Apply f) { return f.template operator()<int>(7); }
template<class F> int via_ptr(F *p) { return p->template operator()<int>(7); }
int qualified(Apply &f) { return f.Apply::template operator()<short>(2); }
struct Table { template<class I> int operator[](I index) const { return index; } };
int index(Table *p) { return p->template operator[]<int>(1); }
int known(Apply &f) { return f.operator()<int>(3); }
int known_base(Apply *p) { return p->Apply::operator()<long>(4); }
namespace lib { template<class T> struct Fun { template<class U> int operator+(U) const; }; }
int specialized(lib::Fun<int> &f) { return f.lib::Fun<int>::operator+<short>(5); }
struct Order { template<class T> bool operator<(T) const; template<class T> int operator>>(T) const; };
bool smaller(Order o) { return o.operator< <int>(6); }
int shift(Order o) { return o.template operator>><int>(8); }
template<class T> struct Late { int operator()(int) const; };
template<class T> int pending(Late<T> &obj) { return obj.template operator()<int>(9); }
struct PairCall { template<class T> T operator()(T a, T b) const; };
int pair(PairCall f) { return f.operator()<>(10, 11); }
