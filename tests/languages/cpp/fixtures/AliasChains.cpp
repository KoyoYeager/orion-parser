namespace left {
    using Base = signed int;
    using Plain = Base;
    using P = Base *;
    using Handle = const P;
    using Read = const Base *;
    using Ref = Base &&;
    using Reference = Base &;
}
namespace right {
    typedef int Plain;
    typedef Plain *const Handle;
    using Read = const int *;
    using Reference = int &;
}
namespace merged { using namespace left; using namespace right; }
merged::Plain plain(merged::Handle p) { return *p; }
merged::Read readonly(merged::Reference r) { return &r; }
