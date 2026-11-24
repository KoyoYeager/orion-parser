auto identity=[](auto x){return x;};
using F=decltype(identity);
int advance(F *p) { return (++p)->operator()<int>(7); }
int retreat(F *p) { return (p--)->operator()<int>(8); }
struct Cursor {
    F &operator++(){return identity;}
    F *operator++(int){return &identity;}
};
int pre(Cursor &c){return (++c).operator()<int>(1);}
int post(Cursor &c){return (c++)->operator()<int>(2);}
namespace lib {
    struct Back { friend F &operator--(Back &){return identity;} };
    F *operator--(Back &,int){return &identity;}
}
int pre_free(lib::Back &b){return (--b).operator()<int>(3);}
int post_free(lib::Back &b){return (b--)->operator()<int>(4);}
int old_pointer(F *p){return (p++)->operator()<int>(5);}
int new_pointer(F *p){return (--p)->operator()<int>(6);}
struct Derived : Cursor {};
int inherited(Derived &d){return (d++)->operator()<long>(9);}
