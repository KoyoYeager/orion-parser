template<class T, T... Values> struct Sequence {};
using Four = __make_integer_seq<Sequence, int, 4>;
template<class T, T N> using Generated = __make_integer_seq<Sequence, T, N>;
