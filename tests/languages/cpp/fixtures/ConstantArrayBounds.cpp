constexpr auto width = sizeof(int);
namespace local {
    constexpr int width{2};
    constexpr int cells = width * ::width;
    using Row = int[width];
    using Block = int[cells];
}
namespace written {
    using Row = int[2];
    using Block = int[8];
}
namespace view { using namespace local; using namespace written; }
void consume(view::Row &, view::Block &);
