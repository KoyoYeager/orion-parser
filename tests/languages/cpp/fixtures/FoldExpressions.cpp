template<class... T>
constexpr auto right(T... xs) { return (xs - ...); }
template<class... T>
constexpr auto left(T... xs) { return (... - xs); }
template<class... T>
constexpr auto sum(T... xs) { return (0 + ... + xs); }
template<class... T>
constexpr auto last(T... xs) { return (xs + ... + 0); }
static_assert(right(9, 4, 1) == 6);
static_assert(left(9, 4, 1) == 4);
static_assert(sum() == 0 && last(1, 2) == 3);

template<class... T>
constexpr auto subtract_left(T... xs) { return (20 - ... - xs); }
template<class... T>
constexpr auto subtract_right(T... xs) { return (xs - ... - 20); }
static_assert(subtract_left(5, 2) == 13);
static_assert(subtract_right(5, 2) == 23);
