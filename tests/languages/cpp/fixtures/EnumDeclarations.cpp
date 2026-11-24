namespace api {
    using Word = unsigned;
    enum class [[nodiscard]] Mode : Word;
    enum Flags : Word;
    struct Owner { enum struct Phase; };
}
enum class api::Mode : api::Word { idle, old [[deprecated("use idle")]] = 9, };
enum api::Flags : api::Word { read = 1, write = read + 1 };
enum struct api::Owner::Phase { start, finish };
api::Mode choose() { return api::Mode::idle; }
int flags() { return api::read + api::Flags::write; }
using idle = int;
namespace copy { using api::Mode; using Alias = Mode; }
int imported() { using enum copy::Alias; return sizeof(idle); }
int local() { enum class Local { idle }; using L = Local; using enum L; return sizeof(idle); }
int outside() { return sizeof(idle); }
int one() { using copy::Alias::idle; return sizeof(idle); }
