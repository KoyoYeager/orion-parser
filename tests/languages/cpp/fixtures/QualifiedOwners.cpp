template<class T, T N> struct Constant {
    static constexpr T value = N;
};
template<class T, T N> constexpr T Constant<T, N>::value;

namespace lib {
    template<class T> struct Box {
        typedef T Element;
        T field;
        T read(Element n) const;
    };
}
template<class U> U lib::Box<U>::read(Element n) const { return field + n; }
int lib::Box<int>::*data = &lib::Box<int>::field;
int (lib::Box<int>::*method)(int) const = &lib::Box<int>::read;

template<class T> struct Cell { int x; };
using Nested = int Cell<Cell<int>>::*;
template<template<class> class Owner> using Get = int Owner<int>::*;
template<int N> struct Count { int x; };
using Computed = int Count<(1 < 2)>::*;
