auto id = [](auto x){ return x; };
using Callable = decltype(id);
int apply(Callable copy) { return copy.operator()<int>(11); }
namespace model { using Ref = Callable const &; using Ptr = Callable *; }
using model::Ptr;
int pointer(Ptr p) { return p->operator()<int>(12); }
int reference(model::Ref f) { return f.operator()<long>(13); }
int deep(Ptr *pp) { return (*pp)->operator()<int>(14); }
struct Holder { using Function = Callable; Function value; };
int field(Holder &h) { return h.value.operator()<int>(15); }
int local() {
    auto inner = [](auto v){ return v; };
    typedef decltype(inner) Alias;
    using Chain = Alias;
    Chain v = inner;
    return v.operator()<int>(16);
}
template<class T> struct Factory { using Alias = Callable; };
int specialized(Factory<int>::Alias f) { return f.operator()<int>(17); }
int ordinary_scope() {
    auto fixed = [](int x){ return x; };
    using Callable = decltype(fixed);
    Callable fn = fixed;
    return fn.operator()(18);
}
