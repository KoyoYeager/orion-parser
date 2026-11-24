[[nodiscard("use result")]] int answer() { return 42; }
using Word = long;
alignas(Word) alignas(16) int aligned;
struct alignas(16) [[maybe_unused]] Box { int member; };
[[using vendor: trace((a + b), [x], {y}), , flag,]] [[vendor::using]] int marker;
int inspect() {
    [[maybe_unused]] int n = answer();
    [[likely]] if (n) return n;
    try { throw n; } catch ([[maybe_unused]] int e) { return e; }
    auto f = []() noexcept [[]] -> int { return 1; };
    int **p = new int*[3] [[]];
    return f();
}

template<class... Types> struct alignas(Types...) TypeAligned {};
template<int... Sizes> struct alignas(Sizes...) ValueAligned {};
[[]];

namespace [[deprecated("old")]] legacy {}
namespace lib { inline namespace abi __attribute__((__abi_tag__("v1"))) {} }
int scoped([[maybe_unused]] int p) {
    if ([[maybe_unused]] int x = p; [[maybe_unused]] int test = x) return test;
    return 0;
}
