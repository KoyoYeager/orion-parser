using Outer = int;

int f(int a) {
    auto scoped = [Outer = a](int v) { return sizeof(Outer) + v; };
    auto param = [](int Outer) { return sizeof(Outer); };
    return sizeof(Outer) + scoped(a) + param(a);
}

struct Box {
    int x;
    int f() {
        return [this] { return x; }() + [*this] { return x; }();
    }
};

template<class... T> int pack(T... args) {
    auto x = [args...] { return (args + ...); };
    auto y = [&args...] { return (args + ...); };
    auto z = [...values = args] { return (values + ...); };
    auto w = [&...refs = args] { return (refs + ...); };
    return x() + y() + z() + w();
}

template<class T> concept Small = sizeof(T) <= sizeof(int);

int constrained() {
    auto f = []<class T> requires Small<T> (T v) noexcept -> int requires Small<T> { return v; };
    return f(2);
}
