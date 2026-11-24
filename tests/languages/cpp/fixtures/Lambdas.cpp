int sum(int base) {
    auto add = [base, total = 0]<class T>(T x) mutable noexcept -> int {
        total += base + x;
        return total;
    };
    return add(2);
}

int captures(int n) {
    auto ref = [&, step = 1]() { return n += step; };
    auto copy = [=, &n] { return n; };
    auto value = [n, &alias = n, factor{2}](int x) constexpr { return n + alias + factor * x; };
    return ref() + copy() + value(2);
}

int immediate() { return []() consteval { return 3; }(); }

int default_only(int x) {
    return [=] { return x; }() + [&] { return x; }();
}

int generic(int n) {
    auto identity = [](auto x) { return x; };
    auto increment = [step(1)](int x) { return x + step; };
    return increment(identity(n));
}

int alternative_tokens(int n) {
    return [bitand n] { return n; }() + [bitand] { return n; }();
}
