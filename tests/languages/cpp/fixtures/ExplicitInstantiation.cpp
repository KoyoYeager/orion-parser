template<class T> struct Data { T value; };
extern template class Data<int>;
template struct Data<long>;

template<class T> T id(T value) { return value; }
template<> int id(int value) { return value + 1; }
template<> long id<long>(long value);
typedef void (*__attribute__((deprecated)) Callback)();
__attribute ((unused)) static int tagged;

template<class T> struct Host { ~Host(); };
template<> Host<int>::~Host() {}
struct Helper { friend int id<>(int); };
