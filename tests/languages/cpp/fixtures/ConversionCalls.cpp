struct Number { explicit operator int() const; };
int value(Number n) { return n.operator int(); }
int pointer_value(Number *p) { return p->Number::operator int(); }
struct Address { operator const int *() const; };
const int *address(Address a) { return a.operator const int *(); }
template<class T> struct Wrapper { operator T() const; };
int unwrap(Wrapper<int> v) { return v.Wrapper<int>::operator int(); }
struct Index {
    using Scalar = int;
    operator Scalar() const;
    Scalar get() const { return operator Scalar(); }
};
Index::Scalar read(Index &i) { return i.Index::operator Index::Scalar(); }
int (Index::*member)() const = &Index::operator int;
template<class T> T dependent(Wrapper<T> &box) { return box.operator T(); }
int first(Address a) { return a.operator const int *()[0]; }
struct Narrow { operator unsigned() const; unsigned get() const; };
unsigned Narrow::get() const { return operator unsigned(); }
template<int N> struct Tag {};
constexpr int Choice = 3;
constexpr int Initial = Choice;
struct Picker { using Choice = int; operator Tag<Initial>(); };
Tag<Choice> (Picker::*pick)() = &Picker::operator Tag<Choice>;
