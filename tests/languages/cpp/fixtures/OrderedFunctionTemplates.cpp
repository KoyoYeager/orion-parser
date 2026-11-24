template<class T> int read(T);
template<class T> int read(T *);
template<int (*F)(int *) = read> struct Handler {};
namespace A { using T = Handler<>; }
namespace B { using T = Handler<&read<int>>; }
namespace C { using namespace A; using namespace B; }
void consume(C::T);
template<class T> int read(T **);
template<int (*F)(int **)> struct Indirect {};
namespace automatic { using U = Indirect<read>; }
namespace named { using U = Indirect<&read<int>>; }
namespace merged { using namespace automatic; using namespace named; }
void consume_deep(merged::U);
