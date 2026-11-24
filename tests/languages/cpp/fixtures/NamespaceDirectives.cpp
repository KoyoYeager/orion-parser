namespace lib { namespace detail { using Word = int; } }
namespace client {
    using namespace lib;
    namespace impl = detail;
    impl::Word value;
}
namespace relay { using namespace lib; }
namespace chained { using namespace relay; namespace implementation = detail; }
namespace direct = relay::detail;
direct::Word use() { using namespace relay; namespace local = detail; local::Word n=1; return n; }
namespace parallel { namespace alias=lib::detail; }
namespace alternatives { namespace alias=lib::detail; }
namespace joined { using namespace parallel; using namespace alternatives; namespace chosen=alias; }
joined::chosen::Word end() { return 2; }
namespace direct_first {
    using namespace lib;
    namespace detail { using Unique = long; }
    namespace selected = detail;
}
direct_first::selected::Unique nearest() { return 3; }
namespace cycle_a { namespace leaf { using Value = int; } }
namespace cycle_b { using namespace cycle_a; }
namespace cycle_a { using namespace cycle_b; }
namespace in_cycle = cycle_b::leaf;
namespace wrapper { inline namespace v1 { inline namespace v2 {using namespace cycle_b;} } }
namespace through_inline = wrapper::leaf;
through_inline::Value by_cycle() { return 4; }
namespace repeated = lib::detail;
namespace repeated = client::impl;
int shadow() { int lib=0; namespace original = lib; original::detail::Word n=2; return n; }
namespace declarations {
    inline namespace version { int available; }
    namespace available = lib::detail;
}
