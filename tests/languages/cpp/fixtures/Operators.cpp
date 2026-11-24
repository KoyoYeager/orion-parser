struct Number {
    int value;
    explicit operator bool() const noexcept;
    operator int() const;
    int operator()(int n) const { return value + n; }
    int operator[](unsigned index) const;
    int operator+(const Number& rhs) const { return value + rhs.value; }
    int operator-(Number) const;
    int operator*(Number) const;
    int operator/(Number) const;
    int operator%(Number) const;
    int operator^(Number) const;
    int operator&(Number) const;
    int operator|(Number) const;
    int operator~() const;
    bool operator!() const;
    Number& operator=(int);
    Number& operator+=(Number);
    Number& operator-=(Number);
    Number& operator*=(Number);
    Number& operator/=(Number);
    Number& operator%=(Number);
    Number& operator^=(Number);
    Number& operator&=(Number);
    Number& operator|=(Number);
    bool operator==(Number) const;
    bool operator!=(Number) const;
    bool operator<(Number) const;
    bool operator>(Number) const;
    bool operator<=(Number) const;
    bool operator>=(Number) const;
    int operator<=>(Number) const;
    bool operator&&(Number) const;
    bool operator||(Number) const;
    int operator<<(int) const;
    int operator>>(int) const;
    Number& operator<<=(int);
    Number& operator>>=(int);
    Number& operator++();
    Number operator--(int);
    int operator,(Number) const;
    const Number* operator->() const;
    int operator->*(int Number::*) const;
    int operator co_await() const;
    static void* operator new(unsigned long);
    static void* operator new[](unsigned long);
    static void operator delete(void*);
    static void operator delete[](void*);
    operator const int*() const { return &value; }
};

Number::operator bool() const noexcept { return value != 0; }
Number::operator int() const { return value; }
int apply_operator(const Number& n) {
    return n.operator()(2) + n.operator+(n);
}

constexpr unsigned long long operator""_twice(unsigned long long n) { return n * 2; }
constexpr unsigned long long operator "" _plus(unsigned long long n) { return n + 1; }
static_assert(2_twice == 4 && 2_plus == 3);
