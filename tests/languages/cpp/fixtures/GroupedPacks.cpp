template<int (*...Callbacks)(int)> struct Calls {
    static_assert(sizeof...(Callbacks) >= 0);
};
template<class... T> void arrays(T (&...values)[2]) {
    static_assert(sizeof...(values) >= 0);
}
