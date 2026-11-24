auto identity = [](auto x){return x;};
using F = decltype(identity);
int assign(F *p, F *q) { return (p = q)->operator()<int>(1); }
int advance(F *p) { return (p += 1)->operator()<int>(2); }
int retreat(F *p) { return (p -= 1)->operator()<int>(3); }
struct Store { F &operator=(int){return identity;} F *operator*=(int){return &identity;} };
int member(Store &s) { return (s = 0).operator()<int>(4) + (s *= 2)->operator()<int>(5); }
namespace api { struct Key {}; F &operator|=(Key &, int){return identity;} }
int adl(api::Key &k) { return (k |= 3).operator()<int>(6); }
int copies(F &f,F g) { return (f=g).operator()<int>(7); }
struct Bits {
    F &operator/=(int){return identity;}
    F &operator%=(int){return identity;}
    F &operator>>=(int){return identity;}
    F &operator<<=(int){return identity;}
    F &operator&=(int){return identity;}
    F &operator^=(int){return identity;}
};
int divide(Bits &b) { return (b /= 2).operator()<int>(8); }
int modulo(Bits &b) { return (b %= 2).operator()<int>(9); }
int right(Bits &b) { return (b >>= 1).operator()<int>(10); }
int left(Bits &b) { return (b <<= 1).operator()<int>(11); }
int mask(Bits &b) { return (b &= 1).operator()<int>(12); }
int toggle(Bits &b) { return (b ^= 1).operator()<int>(13); }
int chained(F *a, F *b, F *c) { return (a=b=c)->operator()<int>(14); }
struct Copy {
    F &operator=(int){ return identity; }
    template<class T> int read() const;
};
int implicit_copy(Copy &a, const Copy &b) { return (a=b).read<int>(); }
struct Custom {
    F &operator=(const Custom &){return identity;}
};
int explicit_copy(Custom &a,const Custom &b) {return (a=b).operator()<int>(15);}
