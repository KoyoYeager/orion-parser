constexpr unsigned long long operator""_num(unsigned long long n){ return n; }
constexpr long double operator""_unit(long double n){ return n; }
constexpr auto decimal = 12'345_num;
constexpr auto octal = 07'1_num;
constexpr auto hex = 0xA'Be_num;
constexpr auto binary = 0B10'01_num;
constexpr auto fraction = .1'25_unit;
constexpr auto decimal_exp = 4'2e1_unit;
constexpr auto hex_fraction = 0x1.8p1_unit;
constexpr auto hex_exp = 0Xf'FP1_unit;
constexpr auto positive = 0x1.8p+1_unit;
constexpr auto negative = 0X.FP-2_unit;
constexpr auto dec_fraction_exp = 3.75E-1_unit;
constexpr auto ordinary = 0x1.8p1L;
constexpr auto suffix_collision = 0xfeedULL;
constexpr auto whole_fraction = 1.e2_unit;
constexpr auto whole_hex_fraction = 0xA.p0_unit;
constexpr auto exponent_separator = 0x1p1'0_unit;
constexpr auto prefixed = 0b1'0u;
constexpr auto leading_zero = 0'7LL;
constexpr auto mixed_case = 42lU;
