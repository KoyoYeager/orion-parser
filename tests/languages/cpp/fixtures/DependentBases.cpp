template<bool, class T> struct Select { using type = T; };
template<class B> struct Derived : Select<B::value, B>::type {};
template<class T> struct Owner {
    template<class U> struct Rebind {};
};
template<class T> struct Rebound : public Owner<T>::template Rebind<int> {};

using Entry = int;
struct Truth { enum : unsigned { off = 0, value = off + 1, }; };
int probe() {
    { enum { Entry = 1 }; static_assert(sizeof(Entry) > 0); }
    return sizeof(Entry);
}

template<class B> struct Direct : B::Base {};
template<class B> struct DirectTemplate : B::template Rebind<int> {};
struct Empty {};
extern Empty existing;
struct FromDecltype : decltype(existing) {};
