using Value = int;
constexpr long measure(Value n) {
    return (long)n + sizeof(Value*) + alignof(Value[3]);
}
constexpr bool safe(Value n) { return noexcept(n + 1); }
unsigned long hidden(int Value) { return sizeof(Value); }
using Callback = int (*)(int);
static_assert(sizeof(int (*)(int)) == sizeof(Callback));
static_assert(safe(4));
