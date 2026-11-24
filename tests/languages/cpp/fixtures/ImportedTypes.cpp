namespace lib { namespace detail { using Word = long; } }
namespace client { using namespace lib; }
client::detail::Word read() { return 7; }
namespace origin {
    struct Box { using Item = int; };
    enum class Kind { one };
}
namespace through { using namespace origin; }
namespace relay { using namespace through; }
using Item = relay::Box::Item;
relay::Kind choice() { return relay::Kind::one; }
namespace first { using Which = int; }
namespace second { using namespace first; constexpr int Which = 3; }
int selected() { return sizeof(second::Which); }
namespace a { using namespace origin; }
namespace b { using namespace origin; }
namespace diamond { using namespace a; using namespace b; }
diamond::Box::Item via_diamond() { return 9; }
namespace side_a { using origin::Box; using Count=int; int call(int); }
namespace side_b { using origin::Box; using Count=signed int; int call(double); }
namespace together { using namespace side_a; using namespace side_b; }
together::Box::Item common(together::Count n) { return together::call(n); }
namespace local_only { namespace { using Entry = int; } constexpr int Entry=5; }
int direct_shadow() { return sizeof(local_only::Entry); }
namespace far { constexpr int Flag=3; }
namespace nearer { using Flag=int; namespace use { using namespace far; int select(){return sizeof(Flag);} } }
