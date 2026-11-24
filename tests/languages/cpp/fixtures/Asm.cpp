asm("");
namespace logging {
    asm("# "
        "namespace");
    int marker(int value) {
        [[]] asm(R"note(# block)note" "\n");
        if (value) asm("# conditional");
        return value;
    }
}
static_assert(1 + 2 == 3, "ordinary " R"msg(raw message)msg");
