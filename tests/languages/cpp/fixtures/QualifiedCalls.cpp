template<class T> struct BaseOps { BaseOps<T> &operator=(const BaseOps<T> &) = default; };
template<class T> struct DerivedOps : BaseOps<T> {
    void assign(const DerivedOps<T> &other) { this->BaseOps<T>::operator=(other); }
};
int reset(int &n) { return n = 0, n + 1; }
struct Point { int x; int y; };
Point origin() { return {0, 0}; }
using NativeSigned = __int128_t;
using NativeUnsigned = __uint128_t;
