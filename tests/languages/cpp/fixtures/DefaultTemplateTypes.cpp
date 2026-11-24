namespace model {
    using Count = short;
    template<class X, class Y = X const *> struct Pair;
    template<class T = Count, class U> struct Pair { U second; };
    template<class T, class U = Pair<T>, class V = U &> struct Chain {};
}
namespace inferred {
    using Count = long;
    using T = model::Pair<>;
    using C = model::Chain<int>;
}
namespace written {
    using T = model::Pair<short, const short *>;
    using C = model::Chain<int, model::Pair<int>, model::Pair<int> &>;
}
namespace both { using namespace inferred; using namespace written; }
void consume(both::T &, both::C &);
