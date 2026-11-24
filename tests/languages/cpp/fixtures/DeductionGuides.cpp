namespace model {
template<class A, class B> struct Duo { A first; B second; };
template<class A, class B> Duo(A a, B b) -> Duo<A, B>;
explicit Duo(int) -> Duo<int, int>;
template<class T> explicit(sizeof(T) > 1) Duo(T *) -> Duo<T, int>;
}

template<class T> using ExprType = __typeof__(T() + T());
template<class T> using WrittenType = __typeof(T *);
unsigned word(float f) { return __builtin_bit_cast(unsigned, f); }
struct Factory { int value; } inline constexpr instance{3};
template<class T> concept Sized = sizeof(T) > 0;
template<class T> struct Wrap {
    int value;
    constexpr explicit(sizeof(T) > 1) Wrap() requires Sized<T> : value(1) {}
};
struct Old { Old() throw() {} };
void legacy() throw();
template<class> struct X; X(int)->X<int>;
template<class T> struct Call { template<class U> int operator()(U); };
template<class T> template<class U> int Call<T>::operator()(U x) { return int(x); }
__extension__ typedef _Complex float ComplexScalar __attribute__((aligned(16)));
int ext(int x __attribute__((__unused__))) { return __extension__ (x + 1); }
