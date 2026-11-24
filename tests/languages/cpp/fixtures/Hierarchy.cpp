struct Base {
    using Value = int;
    explicit Base(Value n) : value(n) {}
    virtual Value score() const noexcept = 0;
    virtual ~Base() = default;
protected:
    Value value;
};
struct Tag {};
class Counter final : public Base, private Tag {
public:
    explicit Counter(Value n);
    Counter() : Counter(0) {}
    Counter(const Counter&) = delete;
    Value score() const noexcept override final;
    ~Counter() override;
};
Counter::Counter(Value n) : Base{n} {}
Base::Value Counter::score() const noexcept { return value + 1; }
Counter::~Counter() = default;
struct Leaf : Tag {};
struct Shared : virtual public Tag {};
struct Pair {
    int x;
    int y;
    explicit Pair(int n) : x(n), y{n} {}
};
