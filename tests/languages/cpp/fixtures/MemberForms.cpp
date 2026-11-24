struct Base { int data; };
enum class Color { red };
struct Members : Base {
    using Base::data;
    using enum Color;
    static_assert(1);
    template<class T> struct Nested { Nested(T); };
    template<> struct Nested<char> {};
    Nested(int) -> Nested<int>;
    enum class Forward : int;
    int x, y;
};
