template<char... Digits> constexpr int operator""_digits() { return sizeof...(Digits); }
constexpr int count = operator""_digits<'1', '2'>();
template<class T> using Pointer = T *;
Pointer<const int> marker;
template<class T> struct Parent {
    template<class U> using Child = U;
    using Item = T;
};
template<class T> using ItemOf = typename T::Item;
template<class T> using ChildOf = typename T::template Child<int>;
using Picked = Parent<int>::template Child<long>;
using ReadOnly = const volatile int *;
template<class T> void consume(T) requires (sizeof(T) > 0);
constexpr auto pointer_bytes = sizeof(const volatile int *);
template<class T> struct Widget { Widget(); };
template<> Widget<int>::Widget();
