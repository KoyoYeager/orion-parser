auto closure = [](auto x) { return x; };
using F = decltype(closure);
F make() { return closure; }
int invoke() { return make().operator()<int>(12); }
F &ref() { return closure; }
auto ptr() -> F * { return &closure; }
int indirect() { return ref().operator()<int>(1) + ptr()->operator()<long>(2); }
struct Factory { F get() const { return closure; } };
int member(const Factory &f) { return f.get().operator()<int>(3); }
auto ordinary = [](int x){return x;};
using Plain = decltype(ordinary);
F select() { return closure; }
Plain select(int) { return ordinary; }
int overload() { return select().operator()<int>(4) + select(1).operator()(5); }
F choose(int) { return closure; }
F choose(double) { return closure; }
int same_result() { return choose(1).operator()<int>(6); }
F with_default(int = 0);
F with_default(int) { return closure; }
F varargs(int, ...) { return closure; }
template<class T> F typed(T) { return closure; }
int extra() { return with_default().operator()<int>(7) + varargs(1, 2).operator()<int>(8) + typed(3).operator()<int>(9); }
struct Builder { using Result = F; auto build() const -> Result; };
auto Builder::build() const -> Result { return closure; }
auto echo(F f) -> decltype(f) { return f; }
int trailing(const Builder &b) { return b.build().operator()<int>(10) + echo(closure).operator()<int>(11); }
Plain route(int) { return ordinary; }
template<class T> F route(T) { return closure; }
F abbreviated(auto) { return closure; }
int explicit_args() { return route<int>(1).operator()<int>(20) + abbreviated<int>(2).operator()<int>(21); }
struct Derived : Factory {};
int qualified(const Derived &d) { return d.Factory::get().operator()<int>(22); }
template<class... Args> int expanded(Args... xs) { return varargs(1, xs...).template operator()<int>(23); }
template<class T> F reverse(T) { return closure; }
Plain reverse(int) { return ordinary; }
int reversed() { return reverse<int>(1).operator()<int>(24); }
template<class T> int adl(T value) { return typed(value).template operator()<int>(25); }
