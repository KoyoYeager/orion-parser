typedef const struct Node { int value; } *ReadPtr, Read;
template<class T> struct Box { T item; };
namespace left {
    using Write = Node *;
    using View = ReadPtr;
    using Grid = Box<Write>[2];
}
namespace right {
    typedef struct Node *Write;
    using View = const Node *;
    using Grid = Box<Node *>[2];
}
namespace merged { using namespace left; using namespace right; }
int sample(merged::Grid &g, merged::View v) {
    merged::Write n = g[0].item;
    return n->value + v->value;
}
