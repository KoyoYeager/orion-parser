template<class... Ts> struct List {};
template<typename T = int, unsigned N = 3> struct Buffer { T values[N]; };
template<typename... Ts> using Types = List<Ts...>;

template<class... Ts>
constexpr auto count(Ts... values) noexcept -> unsigned {
    return sizeof...(values);
}
int variadic(int n, ...);
int only_variadic(...);
constexpr auto size() -> unsigned { return count(1, 2, 3); }
static_assert(size() == 3);
template<template<class...> class C, class... Args>
using Apply = C<Args...>;
template<class... Bases> struct Joined : Bases... {};
using Empty = Apply<List>;
template<template<class...> class C = List>
using Default = C<>;
using DefaultList = Default<>;
