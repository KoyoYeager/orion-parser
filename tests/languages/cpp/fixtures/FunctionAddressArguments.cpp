namespace ops {
    int apply(int);
    long apply(long);
    int checked(int) noexcept;
    struct Entry { int read(int) const; };
}
using Callback = int (*)(int);
template<Callback F = ops::apply, Callback G = F> struct Handler {};
template<int (ops::Entry::*F)(int) const = &ops::Entry::read> struct Member {};
template<auto F> struct Deduced {};
template<class T, T (*F)(T) = ops::apply> struct Selected {};
namespace inferred {
    using Primary = Handler<>;
    using Checked = Handler<ops::checked>;
    using Getter = Member<>;
    using Auto = Deduced<ops::checked>;
    using Long = Selected<long>;
}
namespace written {
    using Primary = Handler<&ops::apply, ops::apply>;
    using Checked = Handler<&ops::checked, ops::checked>;
    using Getter = Member<&ops::Entry::read>;
    using Auto = Deduced<&ops::checked>;
    using Long = Selected<long, &ops::apply>;
}
namespace both { using namespace inferred; using namespace written; }
void consume(both::Primary &, both::Checked &, both::Getter &, both::Auto &, both::Long &);
