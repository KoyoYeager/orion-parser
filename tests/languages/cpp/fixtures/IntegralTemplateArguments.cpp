namespace model {
    constexpr int count = 4;
    template<int N = count, int M = N> struct Size {};
    template<auto N = 4u> struct Deduced {};
    template<class T, T N> struct Typed {};
    template<int N, int M = N + 1> struct Next;
    template<int K = 3, int L> struct Next {};
}
namespace inferred {
    using count = long;
    using S = model::Size<>;
    using Next = model::Next<>;
    using D = model::Deduced<>;
    using Typed = model::Typed<short, 4>;
}
namespace written {
    using S = model::Size<4, 4>;
    using Next = model::Next<3, 4>;
    using D = model::Deduced<4U>;
    using Typed = model::Typed<short, 4U>;
}
namespace both { using namespace inferred; using namespace written; }
void consume(both::S &, both::D &, both::Typed &, both::Next &);
