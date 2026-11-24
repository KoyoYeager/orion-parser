struct Storage {
    struct __attribute__((aligned)) { int size; } slot, extra[2];
    class { public: int count; } item;
    union { int integer; char byte; };
};
namespace options {
    template<class> constexpr bool enabled = true;
}
template<bool> struct Flag {};
template<class T> struct Probe : Flag<options::enabled<T>> {};
template<class T> bool read() { return options::enabled<T>; }
int f(int x){return __alignof__(int) + __alignof__(x);}
template<class T> using Underlying = __underlying_type(T);
template<class T> using Plain = __remove_cv(T);
template<class T> using Value = __remove_cvref(T);
template<class T> using Pointee = __remove_pointer(T *);
template<class T> int width() { return sizeof(__remove_cv(T)); }
int compare(int n) { int enabled = n; return enabled < n; }

using Entry = long;
int injected() {
    { union { int Entry; }; static_assert(sizeof(Entry) == sizeof(int)); }
    return sizeof(Entry);
}
