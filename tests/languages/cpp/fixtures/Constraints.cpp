template<class T> concept Small = sizeof(T) <= sizeof(long);
template<class T, class U> concept Fits = sizeof(T) <= sizeof(U);
template<class T> concept Usable = requires(T x) {
    x + 1;
    typename T::value_type;
    { x.read() } noexcept -> Fits<long>;
    requires Small<T>;
};
template<Small T> requires Small<T> && Fits<T, long>
constexpr T twice(T value) requires (sizeof(T) > 0) { return value + value; }
static_assert(Small<int>);
static_assert(twice(2) == 4);
template<class T>
concept Nested = requires { requires requires(T v) { v.read(); }; };
template<Small T = int>
constexpr auto keep(T value) requires Small<T> || Fits<T, long> { return value; }
constexpr auto abbreviated(Small auto value) { return value; }
using Outer = int;
template<class T>
constexpr int scoped(int Outer) requires (sizeof(Outer) == sizeof(int)) { return Outer; }
static_assert(keep(2) == abbreviated(2));

template<class T> concept Readable = requires(T x) {
    { x.read() };
    { x.read() } -> Small;
};
template<class T> concept Visible = requires(int Outer) { sizeof(Outer); };
static_assert(Visible<int>);
template<class T> constexpr bool can_read() { return (bool)requires(T x) { x.read(); }; }
