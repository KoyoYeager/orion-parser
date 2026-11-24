namespace library::inline v1 {
    enum class Mode : unsigned { quick = 2 };
    using Count = unsigned;
}
namespace api = library;
namespace client {
    using namespace api;
    using enum Mode;
    constexpr Count choose() { return static_cast<Count>(quick); }
}
int run() {
    using api::Count;
    Count result{3};
    return result + client::choose();
}
