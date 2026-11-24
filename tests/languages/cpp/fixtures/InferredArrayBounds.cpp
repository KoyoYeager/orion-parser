namespace sizes {
    struct Holder { int data; int method(int) const; };
    using Member = int Holder::*;
    using Method = int (Holder::*)(int) const;
    Member fields[] = {&Holder::data, nullptr};
    Method methods[] = {nullptr, &Holder::method};
    int transform(int);
    using Callback = int (*)(int);
    Callback callbacks[] = {transform, transform, transform};
    extern Callback callbacks[];
    struct Opaque;
    using Handle = Opaque *;
    Handle handles[] = {nullptr, nullptr};
    extern Handle handles[];
    Handle slots[][2] = {{nullptr}, nullptr, nullptr, nullptr};
    struct Opaque { template<class T> T get(); };
    int read() { return handles[0]->get<int>(); }
    using Row = int[3];
    int flat[] = {1, 2, 3, 4};
    extern int flat[];
    Row mixed[] = {{1}, 2, 3, 4, 5};
    int cube[][2][3] = {1, {2}, 3, {4}, {{5}}};
    int direct[](1, 2, 3);
    const char text[] = {"A\0" "é"};
    char paren_text[]("abc");
    char8_t octets[] = u8"\xC3\xA9";
    char16_t wide[] = u"\U0001F600" uR"(é)";
    char32_t scalar[] = U"\U0001F600";
    int *pointers[] = {nullptr, nullptr};
    char grid[][2][4] = {"a", "b", "c"};
}
namespace inferred {
    using Fields = int[sizeof(sizes::fields)];
    using Methods = int[sizeof(sizes::methods)];
    using Callbacks = int[sizeof(sizes::callbacks)];
    using Handles = int[sizeof(sizes::handles)];
    using Slots = int[sizeof(sizes::slots)];
    using Flat = int[sizeof(sizes::flat)];
    using Mixed = int[sizeof(sizes::mixed)];
    using Cube = int[sizeof(sizes::cube)];
    using Direct = int[sizeof(sizes::direct)];
    using Text = int[sizeof(sizes::text)];
    using ParenText = int[sizeof(sizes::paren_text)];
    using Octets = int[sizeof(sizes::octets)];
    using Wide = int[sizeof(sizes::wide)];
    using Scalar = int[sizeof(sizes::scalar)];
    using Pointers = int[sizeof(sizes::pointers)];
    using Grid = int[sizeof(sizes::grid)];
}
namespace expected {
    using Fields = int[16]; using Methods = int[32];
    using Callbacks = int[24]; using Handles = int[16]; using Slots = int[48];
    using Flat = int[16]; using Mixed = int[36]; using Cube = int[48];
    using Direct = int[12]; using Text = int[5]; using Wide = int[8];
    using ParenText = int[4]; using Octets = int[3];
    using Scalar = int[8]; using Pointers = int[16]; using Grid = int[16];
}
namespace both { using namespace inferred; using namespace expected; }
void accept(both::Fields &, both::Methods &, both::Callbacks &, both::Handles &, both::Slots &, both::Flat &, both::Mixed &, both::Cube &, both::Direct &, both::Text &,
            both::ParenText &, both::Octets &, both::Wide &, both::Scalar &, both::Pointers &, both::Grid &);
