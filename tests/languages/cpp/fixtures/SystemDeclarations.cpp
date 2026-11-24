namespace tags {
    enum Kind { first };
    struct Stamp { int tick; };
}
using tags::Kind;
struct Owner { enum Kind type; };
int set(int fd, const struct tags::Stamp [2]);
using Record = struct tags::Stamp;
typedef unsigned short Count, *CountPtr, Counts[2];
typedef __signed__ char SignedByte;
struct Path {
    using Text = int;
    Path &operator=(Text &&);
    int assign(Text &&);
};
Path &Path::operator=(Text &&value) { return *this; }
int Path::assign(Text &&value) { return value; }

template<class T> struct Later {
    Later(int x) : index(static_cast<Index>(x)), extra{sizeof(Index)} {}
    using Index = int;
    Index index;
    unsigned long extra;
};
namespace outer { inline namespace v { namespace detail { using Item = long; } } }
namespace other { using Item = short; }
int local_alias() {
    namespace select = outer::detail;
    select::Item value = 1;
    { namespace select = other; select::Item n = 2; value += n; }
    return value;
}
struct Source { operator int() const { return 1; } Source &operator=(int); };
struct Destination : Source { using Source::operator int; using Source::operator=; };
template<class T> T make();
template<class T> using Result = typename decltype(make<T>())::type;
void qualified_ref(int &__restrict x) { x = 0; }
namespace tag { struct X {}; }
struct Storage {
    union { tag::X x; };
    void destroy() { x.~X(); }
};

struct Invoke {
    void operator()(int n) { operator()<int>(n); }
    template<class T> void operator()(T) {}
};
template<class T> bool dependent_value() { return decltype(make<T>())::value; }
