namespace audit {
template<class T> struct Reader {
    template<class U> int read(U x) {
        Later n = x;
        if (enabled<U>) return n;
        return 0;
    }
    int shadow(int n) { int enabled = n; return enabled < n; }
    struct Nested { bool test() const { return enabled<T>; } };
    using Later = int;
    template<class> static constexpr bool enabled = true;
};
}

struct Outer { struct Inner; };
struct Outer::Inner { int value; };

int build(int n) {
    struct Guard { explicit Guard(int x) : value(x) {} int value; } g(n);
    return g.value;
}

template<class T> struct Traits { struct Nested { static constexpr int value = 1; }; };
template<class T> struct Use { static constexpr int count = Traits<T>::Nested::value; };
