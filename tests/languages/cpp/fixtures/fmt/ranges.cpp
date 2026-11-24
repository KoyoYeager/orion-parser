#include <fmt/ranges.h>
int main() {
  int values[] = {1, 2, 3};
  return fmt::format("{}", values) == "[1, 2, 3]" ? 0 : 1;
}
