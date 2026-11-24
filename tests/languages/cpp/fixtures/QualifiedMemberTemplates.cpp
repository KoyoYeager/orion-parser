struct Base { template<class T> int get() const; };
struct Derived : Base {};
int read(Derived const &v) { return v.Base::template get<int>(); }
template<class T> int indirect(T *p) { return p->T::template get<int>(); }
namespace lib {
    template<class U> struct Holder { template<class T, int N> int sum() const; };
}
int total(lib::Holder<char> *p) { return p->lib::Holder<char>::template sum<long, 3>(); }
int known(Derived const &v) { return v.Base::get<unsigned>(); }
int known_specialization(lib::Holder<char> *p) { return p->lib::Holder<char>::sum<int, 4>(); }
struct Data { int field; };
bool less(Data const &d, int limit) { return d.Data::field < limit; }
struct T { int get; };
template<class T> int shadow(T &obj) { return obj.T::template get<2>(); }
bool greater(const Data &d, int limit) { return d.Data::field > limit; }
bool at_least(const Data &d, int limit) { return d.Data::field >= limit; }
bool at_most(const Data &d, int limit) { return d.Data::field <= limit; }
int nested_args(const Base &b) { return b.Base::get<lib::Holder<unsigned>>(); }
