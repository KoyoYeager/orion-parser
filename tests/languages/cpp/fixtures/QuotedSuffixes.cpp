constexpr unsigned long operator""_len(const char *, unsigned long n){return n;}
constexpr int operator""_code(char c){return c;}
constexpr auto first = "a"_len "bc";
constexpr auto last = "a" R"tag(b c)tag"_len;
constexpr auto both = R"(a)"_len "" "b"_len;
constexpr auto ordinary = "a" "b";
constexpr auto character = 'A'_code;
constexpr unsigned long operator""_len(const wchar_t*, unsigned long n){return n;}
constexpr auto wide = "w" LR"x(ide)x"_len;
constexpr auto utf8 = u8"a" "b";
constexpr auto utf16 = "a" u"b" uR"(c)";
constexpr auto utf32 = UR"(a)" "b";
constexpr auto scalar = U'\U0001F642';
constexpr auto controls = u"\u0000" "\u0041";
constexpr auto raw_escape = UR"(\uD800)";
constexpr auto boundary = U"\U0010FFFF";
