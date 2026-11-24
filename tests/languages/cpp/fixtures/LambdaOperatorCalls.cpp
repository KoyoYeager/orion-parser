int invoke() {
    auto id = []<class T>(T value) { return value; };
    return id.operator()<int>(3);
}
int aliases() {
    auto id = [](auto value) { return value; };
    auto copy = id;
    const auto &alias{copy};
    auto *pointer = &id;
    return alias.operator()<int>(1) + pointer->operator()<long>(2);
}
int captured() {
    auto id = []<class T>(T value) { return value; };
    auto run = [id, duplicate=id](){ return id.operator()<int>(3) + duplicate.operator()<int>(4); };
    return run();
}
int immediate() { return ([](auto x){ return x; }).operator()<int>(5); }
int shadow() {
    auto id = [](auto x) { return x; };
    { auto id = [](int x) { return x; }; id.operator()(6); }
    return id.operator()<int>(7);
}
int retained() {
    auto id = [](auto x) { return x; };
    decltype(auto) ref = (id);
    return ref.operator()<int>(8);
}
int direct_copy() {
    auto original{[](auto x){return x;}};
    auto copy(original);
    return copy.operator()<int>(9);
}
struct Registry { inline static auto id = [](auto x){return x;}; };
int from_class() { return Registry::id.operator()<int>(10); }
