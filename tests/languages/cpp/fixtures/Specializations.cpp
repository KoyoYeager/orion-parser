template<class... Ts> struct Choice { using Primary = long; };
template<> struct Choice<> { using Selected = int; static int read(Selected); };
template<class T> struct Choice<T> { using Item = T; Item get(Item x) { return x; } };
int Choice<>::read(Selected x) { return x; }

template<class T> struct Tag { using Label = int; };
template<> struct Tag<long> { int Label; int value(); };
template<> struct Tag<int> { using Label = short; int value(); };
int Tag<int>::value() { return sizeof(Label); }
int Tag<long>::value() { return sizeof(Label); }

template<class T> struct Tag<T *> { using Entry = T; static int size(Entry); };
template<class V> int Tag<V *>::size(Entry n) { return sizeof(n); }
