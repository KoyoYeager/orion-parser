#include <coroutine>

struct Pair { int x, y; };
struct Awaiter {
    bool await_ready();
    void await_suspend(std::coroutine_handle<>);
    int await_resume();
};
struct Sequence {
    struct promise_type {
        Sequence get_return_object();
        std::suspend_never initial_suspend();
        std::suspend_never final_suspend() noexcept;
        Awaiter yield_value(int);
        Awaiter yield_value(Pair);
        void return_void();
        void unhandled_exception();
    };
};
struct Result {
    struct promise_type {
        Result get_return_object();
        std::suspend_never initial_suspend();
        std::suspend_never final_suspend() noexcept;
        void return_value(Pair);
        void unhandled_exception();
    };
};

Sequence coro_case_sequence(Awaiter a, int n) {
    n = co_await a + 2;
    co_yield n = 3;
    co_yield {n, n + 1};
    auto twice = [](int x) { return x + x; };
    try { (void)twice(n); } catch (...) { co_return; }
    co_return;
}
Result coro_case_result(Awaiter a) {
    co_return {co_await a, 4};
}
Result coro_case_value(Pair p) { co_return p; }

struct Worker {
    Sequence coro_case_member() {
        Later value = 2;
        co_yield value;
        co_return;
    }
    using Later = int;
};
