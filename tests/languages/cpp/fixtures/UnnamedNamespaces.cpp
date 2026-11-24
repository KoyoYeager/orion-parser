namespace outer {
    inline namespace { using Word = int; Word n = 3; }
    namespace { Word next() { return n; } }
    Word read() { return next(); }
}
namespace other {
    namespace { using Word = long; struct State { Word value; }; }
    namespace { State state; namespace inner {using Size = unsigned;} }
}
outer::Word first() { return outer::n; }
other::Word second() { return other::state.value; }
namespace alias = other::inner;
alias::Size nested() { return 4; }
namespace wrappers::inline version::detail { using Size = long; }
wrappers::detail::Size version_size() { return 5; }
namespace words { namespace [[vendor::local]] { using Choice = int; } }
namespace values { namespace { constexpr int Choice = 5; } }
int lookup() { return sizeof(words::Choice) + sizeof(values::Choice); }
namespace attributed { inline namespace [[vendor::local]] { using Token = int; } }
attributed::Token token() { return 6; }
