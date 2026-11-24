namespace names { using A = int; using B = long; }
using names::A, names::B;

template<class T> struct Base { using Type = T; static constexpr int value = 2; };
template<class T> struct Derived : public Base<T> {
    using typename Base<T>::Type;
    using Base<T>::value;
    Type get(Type x) { return x + value; }
};
template<class... Parents> struct Joined : Parents... { using Parents::get...; };

template<class> struct Wide {};
__extension__ template<> struct Wide<unsigned __int128> {} __attribute__((deprecated("wide")));
struct __attribute__((deprecated("old"))) Legacy {};
