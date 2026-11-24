auto generic = [](auto x){return x;};
auto plain = [](int x){return x;};
decltype(generic) select(double) { return generic; }
decltype(plain) select(int) { return plain; }
int use(){return select(1.0).operator()<int>(4);}
decltype(generic) promote(double, int = 0) { return generic; }
decltype(plain) promote(long, int = 0) { return plain; }
int use_promotion(){return promote(1.0f).operator()<int>(5);}
struct Token { operator int() const { return 1; } };
decltype(generic) converted(int) { return generic; }
decltype(plain) converted(double) { return plain; }
int use_conversion(Token t){return converted(t).operator()<int>(7);}
struct Accepted { Accepted(int); };
struct Wrong {};
decltype(generic) construct(Accepted) { return generic; }
decltype(plain) construct(Wrong) { return plain; }
int use_constructor(){return construct(1).operator()<int>(8);}
decltype(generic) ref_pick(int &) { return generic; }
decltype(plain) ref_pick(const int &) { return plain; }
int use_reference(int &n){return ref_pick(n).operator()<int>(9);}
template<class T> concept Small = sizeof(T) <= 8;
template<class T> concept Medium = Small<T> && (sizeof(T) > 1);
template<Small T> decltype(plain)& by_concept(T) { return plain; }
template<Medium T> decltype(generic)& by_concept(T) { return generic; }
int use_concept(){return by_concept(3).operator()<int>(10);}
auto factory() { return [](auto x){return x;}; }
int deduced_factory() { return factory().operator()<int>(11); }
int nested_factory() {
    auto make = [] { auto local = []<class>(int v){return v;}; return local; };
    return make().operator()<long>(12);
}
