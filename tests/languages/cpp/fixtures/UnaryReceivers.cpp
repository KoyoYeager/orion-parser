auto identity=[](auto x){return x;};
using F=decltype(identity);
struct Handle {
    F &operator*(){return identity;}
    F *operator&(){return &identity;}
    F &operator+(){return identity;}
};
int deref(Handle &h){return (*h).operator()<int>(1);}
int address(Handle &h){return (&h)->operator()<int>(2);}
int positive(Handle &h){return (+h).operator()<int>(3);}
namespace lib {
    struct Bits { friend F *operator!(Bits){return &identity;} };
    F &operator~(Bits){return identity;}
    F *operator-(Bits){return &identity;}
}
int negate(lib::Bits b){return (not b)->operator()<int>(4);}
int invert(lib::Bits b){return (compl b).operator()<int>(5);}
int negative(lib::Bits b){return (-b)->operator()<int>(6);}
int builtin(F *p){return (+p)->operator()<int>(7);}
