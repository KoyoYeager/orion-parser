template<class T> T identity(T x) { return x; }
extern template int identity(int);
template long identity<long>(long);
template<class T> int size = sizeof(T);
template int size<int>;
