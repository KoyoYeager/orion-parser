typedef struct { int quotient, remainder; } Div, *DivPtr, DivPair[2];
DivPtr select(DivPair &values) { return &values[0]; }
typedef union Number { int i; float f; } NumberAlias;
template<class T> struct Box {
    using Size = int;
    Box(T seed, Size n);
    ~Box();
    T value;
};
template<class U> Box<U>::Box(U seed, Size n) : value(seed + n) {}
template<class U> Box<U>::~Box() {}

struct Node;
static __inline int get(struct Node *__restrict p, int **__restrict__ end) { return end != nullptr; }
struct Flags {
    unsigned ready : 1 = 0, : 2, mode : 3 {2};
    int plain, value : 4;
    int : 0;
};
int bit_source;
struct Widths {
    int first : true ? 4 : bit_source = 2;
    int second : (true ? 4 : bit_source) = 2;
};
extern "C" int local_name(int) __asm__("external_entry");
template<class T> T make_value() { return T(static_cast<const T::rep &>(-1), 1); }
