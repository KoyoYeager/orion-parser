namespace n { class Known; template<class> struct Box; }
template<class T> struct Host {
  friend class Hidden;
  friend struct n::Box<int>;
  friend class T::Nested;
  friend T;
  friend int;
  template<class U> friend class Peer;
};
class PeerHost { friend class VisibleLater; };
class VisibleLater;
VisibleLater *peer();
struct Base { virtual int value() { return 0; } };
struct Derived : Base { int number; };
int casts(Base *b, const int *p, void *raw) {
    return static_cast<Derived &>(*b).number + dynamic_cast<Derived *>(b)->number
        + const_cast<int *>(p)[1] + reinterpret_cast<unsigned char (*)[3]>(raw)[0][2];
}
inline constexpr struct Make { int operator()() const { return 1; } } maker{};
template<unsigned I, class... T> using At = __type_pack_element<I,T...>;

template<class T> struct Check {
    template<class U> static constexpr bool test() { return true; }
};
template<bool> struct Condition {};
template<class T> struct Checked : Condition<Check<T>::template test<int>()> {};
struct Callable { int operator() [[nodiscard]] (int x [[maybe_unused]]) const { return x; } };
