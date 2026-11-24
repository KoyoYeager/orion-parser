struct Point { int x, y; };
struct Box { Point corner; int size; };
Box placed(int value) { return {.corner = {.y = value}, .size{value + 1},}; }
template<class T> T dependent(int value) { return T{.x = value, .y{2}}; }
