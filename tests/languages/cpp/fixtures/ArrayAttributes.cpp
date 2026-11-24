int grid [[maybe_unused]] [2] [[example::outer]] [3] [4] [[example::inner]];
using Row = int[5] [[example::row]];
template<class... T> void named(T ...values [[maybe_unused]] [2] [[example::dim]]);
template<class... T> void unnamed(T ...[3] [[example::anonymous]]);
template<class... T> void grouped(T (&...values [[maybe_unused]])[4] [[example::ref]]);
template<int (*...F [[example::callback]])(int)> struct Call {};
struct Entry { int field; } entries [[example::object]] [3] [[example::records]];
