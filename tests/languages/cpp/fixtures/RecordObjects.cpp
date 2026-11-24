struct Row { int value; } row{3}, *pointer = &row, (&ref) = row;
using RowArray = struct Element { int n; }[2];
using Node = struct Detail { using Size = int; Size count; };
Node::Size read() { return pointer->value + ref.value; }
struct Item { int number; } items[2] = {{1}, {2}}, (*array_pointer)[2] = &items;
typedef const struct Packet { int size; } PacketView, *PacketPtr;
typedef struct Tag { int n; } volatile TagView;
