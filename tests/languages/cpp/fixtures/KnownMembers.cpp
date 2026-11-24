struct Access { template<class T> T get() const; };
struct Derived : Access {};
struct Wrapper { Derived object; };
struct Compare { int get; };

template<class T> T read(const Access &a, const Derived *ptr, Wrapper &w) {
    return a.get<T>() + ptr->get<T>() + w.object.get<T>();
}
bool less(const Compare &c, int n, int m) { return c.get < n > m; }

template<bool, class T, class U> struct Select { using type = T; };
template<class T, class U> struct Select<0, T, U> { using type = U; };
typedef Select<true, long, short>::type First;

template<class T> struct Enclosing { struct Inner; };
template<class U> struct Enclosing<U>::Inner {
    Inner(int n);
    int value;
};
template<class T> Enclosing<T>::Inner::Inner(int n) : value(n) {}

namespace names { template<class> struct Peer; }
struct Host { template<class T> friend struct names::Peer; };
struct Parent { int answer() { return 42; } };
struct Child : Parent {};
int named(Child &c) { return c.Parent::answer(); }
template<class T> T dereference(Access *ptr) { return (*ptr).get<T>(); }

template<class A, class B> struct Vec;
template<class A> struct Vec<bool, A> { using Item = int; template<class I> void fill(I); };
template<class A> template<class I> void Vec<bool, A>::fill(I) { Item n; }
