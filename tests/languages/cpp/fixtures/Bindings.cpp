struct Pair { int first; int second; };
using Name = long;
int bindings(Pair &pair, Pair (&rows)[2]) {
    auto &[Name, extra] = pair;
    int n = sizeof(Name);
    if (const auto &[a, b] = pair; a < b) n += a;
    for (int offset = extra; auto &[x, y] : rows) n += x + y + offset;
    return n;
}

struct One { int member; };
int singleton(One &one) {
    auto &[first](one);
    auto &[second]{one};
    return first + second;
}
