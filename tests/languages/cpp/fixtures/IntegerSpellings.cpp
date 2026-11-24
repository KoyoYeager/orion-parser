constexpr int binary[3] = {0b0, 0B1, 0b1'0};
constexpr int octal[9] = {0, 00, 01, 02, 03, 04, 05, 06, 0'7};
constexpr int decimal[10] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 1'0};
constexpr int hexadecimal[23] = {
    0x0, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9,
    0xa, 0xb, 0xc, 0xd, 0xe, 0xf, 0XA, 0XB, 0XC, 0XD, 0XE, 0XF, 0xA'F
};
constexpr unsigned long long suffixes[4] = {1uL, 1Ull, 1lU, 1LLu};
constexpr bool flags[2] = {true, false};
static_assert(binary[2] == 2 && octal[8] == 7 && decimal[9] == 10);
static_assert(hexadecimal[15] == hexadecimal[21] && hexadecimal[22] == 175);
static_assert(suffixes[0] == suffixes[3] && flags[0] && !flags[1]);
