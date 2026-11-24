#include <fmt/chrono.h>
int main() {
  return fmt::format("{}", std::chrono::seconds{2}) == "2s" ? 0 : 1;
}
