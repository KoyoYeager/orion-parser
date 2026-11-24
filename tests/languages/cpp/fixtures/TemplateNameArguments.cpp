template<class T> struct Provider { template<class U> using Rebind = U; };
template<template<class> class Factory> struct Apply { using type = Factory<int>; };
template<class T> using Result = typename Apply<Provider<T>::template Rebind>::type;
template<class T> using Direct = Apply<T::template Rebind>;
template<template<class...> class Op, class... Ts>
concept CanApply = requires { typename Op<Ts...>; };
template<class T> int inspect(typename Provider<T>::template Rebind<int> &x) { return x; }
