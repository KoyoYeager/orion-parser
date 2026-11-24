auto identity=[](auto x){return x;};
using F=decltype(identity);
struct Flags {
    F &operator*(int) const {return identity;}
    F *operator/(int) const {return &identity;}
    F &operator%(int) const {return identity;}
    F *operator<<(int) const {return &identity;}
    F &operator>>(int) const {return identity;}
    F *operator&(int) const {return &identity;}
    F &operator^(int) const {return identity;}
    F *operator|(int) const {return &identity;}
    F &operator==(int) const {return identity;}
    F *operator!=(int) const {return &identity;}
    F &operator<(int) const {return identity;}
    F *operator>(int) const {return &identity;}
    F &operator<=(int) const {return identity;}
    F *operator>=(int) const {return &identity;}
    F &operator<=>(int) const {return identity;}
    F *operator&&(int) const {return &identity;}
    F &operator||(int) const {return identity;}
};
int multiply(const Flags &f) { return (f * 2).operator()<int>(1); }
int divide(const Flags &f) { return (f / 2)->operator()<int>(2); }
int modulo(const Flags &f) { return (f % 2).operator()<int>(3); }
int shift_left(const Flags &f) { return (f << 2)->operator()<int>(4); }
int shift_right(const Flags &f) { return (f >> 2).operator()<int>(5); }
int bits_and(const Flags &f) { return (f & 2)->operator()<int>(6); }
int bits_xor(const Flags &f) { return (f ^ 2).operator()<int>(7); }
int bits_or(const Flags &f) { return (f | 2)->operator()<int>(8); }
int equal(const Flags &f) { return (f == 2).operator()<int>(9); }
int unequal(const Flags &f) { return (f != 2)->operator()<int>(10); }
int less(const Flags &f) { return (f < 2).operator()<int>(11); }
int greater(const Flags &f) { return (f > 2)->operator()<int>(12); }
int less_equal(const Flags &f) { return (f <= 2).operator()<int>(13); }
int greater_equal(const Flags &f) { return (f >= 2)->operator()<int>(14); }
int compare(const Flags &f) { return (f <=> 2).operator()<int>(15); }
int logical_and(const Flags &f) { return (f && 2)->operator()<int>(16); }
int logical_or(const Flags &f) { return (f || 2).operator()<int>(17); }
namespace api { struct Item {}; F &operator*(int,Item){return identity;} }
int found(api::Item item){return (2 * item).operator()<int>(18);}
F *operator+(int, F &x){return &x;}
int chained(const Flags &f) { return (1 + f * 2)->operator()<int>(19); }
