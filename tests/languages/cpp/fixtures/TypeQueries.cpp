import <typeinfo>;

using Value = int;
bool same_type(Value x) {
    return typeid(x) == typeid(Value);
}
