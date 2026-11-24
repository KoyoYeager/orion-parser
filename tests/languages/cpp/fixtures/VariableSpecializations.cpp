template<class T> constexpr bool ref = false;
template<class U> constexpr bool ref<U &> = true;
template<> constexpr bool ref<void> = false;
static_assert(ref<int &>);
struct Call {
    template<class> static constexpr bool safe() { return true; }
    template<class T> void operator()(T) const noexcept(safe<T>()) {}
};
template<int N> constexpr int rec = rec<N - 1>; template<> constexpr int rec<0> = 0;
