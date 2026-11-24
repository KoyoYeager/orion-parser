enum class Kind : unsigned { first, second } selected = Kind::first, *pointer = &selected;
typedef enum Legacy { zero, one } Legacy, *LegacyPtr;
using Modern = enum class Named { item };
const enum Bits { bit = 1 } bits[1] = {bit};
LegacyPtr take(Legacy *p) { return p; }
using Values = enum Fresh { low, high }[2];
struct Holder { enum Flag { on = 1 } flag : 2; enum Padding { pad } : 1; };
int local_enum() {
    enum Local { base = 2 } value = base, *p = &value;
    return *p;
}
