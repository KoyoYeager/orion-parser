namespace data {
    struct Entry { int field; };
    inline Entry entry;
    constexpr auto entry_pointer = &entry;
    inline int item, samples[2];
    constexpr int &alias = item;
    constexpr auto pointer = &alias;
}
namespace imported { using data::item; }
template<int *P = &imported::item, int *Q = P> struct Pair {};
template<int &R> struct Reference {};
template<auto P> struct Address {};
template<data::Entry *P = &data::entry> struct Object {};
template<int data::Entry::*P = &data::Entry::field> struct Member {};
namespace inferred {
    using T = Pair<>;
    using E = Object<>;
    using F = Member<>;
    using R = Reference<data::alias>;
    using Element = Address<data::samples>;
}
namespace explicit_args {
    using T = Pair<data::pointer, &data::item>;
    using E = Object<data::entry_pointer>;
    using F = Member<&data::Entry::field>;
    using R = Reference<imported::item>;
    using Element = Address<&data::samples[0]>;
}
namespace shared { using namespace inferred; using namespace explicit_args; }
void consume(shared::T &, shared::R &, shared::Element &, shared::E &, shared::F &);
