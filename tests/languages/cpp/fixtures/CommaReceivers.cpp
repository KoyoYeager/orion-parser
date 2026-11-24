auto identity = [](auto x){return x;};
using F = decltype(identity);
int builtin(F &f) { return (void(), f).operator()<int>(7); }
int pointer(int mark, F *p) { return ((void)mark, p)->operator()<int>(8); }
struct Store { F &operator,(int) { return identity; } };
int member(Store &s) { return (s, 1).operator()<int>(9); }
namespace lib {
    struct Key {};
    F *operator,(int, Key) { return &identity; }
}
int nonmember(lib::Key k) { return (1, k)->operator()<int>(10); }
int nested(Store &s) { return (void(), (s, 2)).operator()<int>(11); }
namespace lib {
    struct Other {};
    int fallback(Other o, F &f) { return (o, f).operator()<int>(11); }
    struct Friend { friend F &operator,(int, Friend) { return identity; } };
}
int hidden(lib::Friend value) { return (1, value).operator()<int>(12); }
namespace conversion {
    F *operator,(long, F &v) { return &v; }
    int run(F &v) { return (1L, v)->operator()<long>(13); }
}
void discard() {}
int discarded(F &f) { return (discard(), f).operator()<short>(14); }
