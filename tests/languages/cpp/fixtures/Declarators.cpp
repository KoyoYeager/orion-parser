using Callback = int (*)(int);
typedef int (&Three)[3];
using Table = int (*[2])(int);

int increment(int value) { return value + 1; }
int (*factory(bool enabled))(int) { return enabled ? increment : nullptr; }
int (*const callbacks[2])(int) = {increment, increment};
int values[3] = {1, 2, 3};
int (&view)[3] = values;

int apply(int (*fn)(int), int (&items)[3]) { return fn(items[1]); }
int run() { return apply(factory(true), view); }

using Element = int;
using Unary = int(Element);
int apply_unnamed(int (*)(int), int = 1);
int declares_function(int (Element));
int choose() {
    int object(Element(2));
    int declaration(Element());
    return object;
}
int folded() {
    int inputs[2] = {1, 2};
    int result(0);
    for (int value : inputs) result += value;
    return result;
}
using Rvalue = int&&;
int (*volatile slot)(int) = increment;
