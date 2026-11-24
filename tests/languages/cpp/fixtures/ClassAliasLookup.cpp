typedef __builtin_va_list Args;
typedef struct RootRecord { using Value = long; } Root __attribute__((aligned));
struct Other { using Value = short; };

struct Limits {
    using S = Root;
    using Chain = S;
    static long run() {
        long first = static_cast<Chain::Value>(1);
        { using S = Other; S::Value small = 2; first += small; }
        return first + sizeof(S::Value);
    }
};
template<class T> T copy(T input) { return decltype(input){input}; }
template<class T> struct View {
    operator int() const requires (sizeof(T) > 1);
    explicit operator bool() const requires requires(T x) { x.empty(); } { return true; }
};
inline int __attribute__((always_inline)) inc(int n) { return n + 1; }
inline __attribute__((always_inline)) constexpr int twice(int n) { return 2*n; }
using OldRep [[deprecated("use long")]] = long;
using ExtensionRep __attribute__((deprecated("use int"))) = int;
struct Wrapper { using Member = Root; };
using Parent = Wrapper;
using ViaTwoOwners = Parent::Member::Value;
