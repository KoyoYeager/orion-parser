#include <fmt/std.h>
int main() {
  return fmt::format("{}", std::bitset<4>{3}) == "0011" ? 0 : 1;
}
