template<class T> T apply(T);
template<class T> T load(const T *);
template<class T, class U = T> T convert(U);
template<int (*F)(int) = apply> struct Handler {};
template<class T, T (*F)(T) = apply> struct Selected {};
template<int (*F)(const int *)> struct Reader {};
namespace inferred {
    using T = Handler<>;
    using Long = Selected<long>;
    using Read = Reader<load>;
    using Converted = Handler<convert<int>>;
}
namespace written {
    using T = Handler<&apply<int>>;
    using Long = Selected<long, &apply<long>>;
    using Read = Reader<&load<int>>;
    using Converted = Handler<&convert<int, int>>;
}
namespace both { using namespace inferred; using namespace written; }
void consume(both::T &, both::Long &, both::Read &, both::Converted &);
