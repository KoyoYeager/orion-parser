template<class T, unsigned = sizeof(T)> int size_of(T) { return sizeof(T); }
template<int...> struct Numbers {};
template<int (*)(int) = nullptr, int (*Fn)(int) = nullptr> struct Callbacks {};
using Value = int;
template<int Value, unsigned = sizeof(Value)> struct Shadow {};
template<class T> struct Promote { using type = T; };
template<class... T> auto sum() { return (typename Promote<T>::type(0) + ...); }
template<class T> auto make() { return typename Promote<T>::type{1}; }

template<bool> struct Flag {};
template<class T> struct Signed : Flag<T(-1) < T(0)> {};

template<class T> void destroy(T &item, T *ptr) { item.~T(); ptr->~T(); }
template<class, class> struct Pair {};
template<class T, class U> using ArrayPointers = Pair<T (*)[], U (*)[]>;

template<int Values[3]> struct Extent {};
template<int = {1}> struct BracedDefault {};

template<class T> struct EmptyCast : Flag<T() < T(0)> {};
template<class T> using FunctionType = Pair<T(), T()>;
template<class T> void reset(T value) { value.~decltype(value)(); }
