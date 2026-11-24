[[]];
thread_local int per_thread;
extern const int external_value;
inline constinit int seed = 3;
consteval int initial() { return 1; }
typedef int Count;
template<class T> struct Wrap { using Item = T; };
union Cell { mutable int data; };
struct Owner {
    friend class Friend;
    constexpr static int count = 1;
};
struct Wrap<int> *wrapped;
int run() {
    enum class Forward : int;
    const Count value = initial();
    ;
    return value;
}
using Alias = struct Wrap<int>;
using Ref = struct Wrap<int> &;
struct Wrap<Wrap<int>> *nested;
struct Wrap<int> (*factory)();
void take(struct Wrap<int>);
