auto generic = [](auto x){return x;};
namespace library { template<class T> struct Box {}; }
namespace app { struct Key {}; decltype(generic)& operator+(library::Box<Key>, int) { return generic; } }
int run(library::Box<app::Key> x) { return (x + 1).operator()<int>(3); }
auto plain = [](int x){ return x; };
namespace app {
    decltype(plain)& operator+(library::Box<Key>, double) { return plain; }
    struct Count { operator int() const { return 2; } };
}
int second(library::Box<app::Key> x, app::Count y) { return (x + y).operator()<int>(4); }
library::Box<app::Key> make() { return {}; }
int temporary() { return (make() + 1).operator()<int>(5); }
namespace base {
    struct Root {};
    decltype(generic)& operator-(Root, int) { return generic; }
}
namespace leaf { struct Child : base::Root {}; }
int inherited(leaf::Child x) { return (x - 1).operator()<int>(6); }
