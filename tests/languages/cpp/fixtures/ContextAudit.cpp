struct Slot {
    static void *operator new[](unsigned long);
    static void operator delete[](void *);
};
Slot (*create(int n))[3] { return new Slot[n][[vendor::count]][3][[vendor::inner]]; }
enum { low, high } first = low, second = high;
int use() { enum { a, b } item = b; return item; }
struct X {};
using Y = X;
void destroy(Y *p) { (p->Y::~Y)(); }
template<class T> struct Outer {
    template<class U> struct Inner { Inner(); ~Inner(); U get(); };
};
template<class T> template<class U> Outer<T>::Inner<U>::Inner() {}
template<class T> template<class U> Outer<T>::Inner<U>::~Inner() {}
template<class T> template<class U> U Outer<T>::Inner<U>::get() { return U{}; }
template<class T> struct Box { static constexpr int tag = 2; };
template<class T> struct Box<T *> { using tag = long; };
int f() { return sizeof(Box<int *>::tag); }
template<class T> struct Grant { friend class T::template View<int>; };
struct Family { template<class> class View {}; };
Grant<Family> grant;
template<class... T> struct Many { static constexpr int id=0; };
template<class T,class... Rest> struct Many<T *, Rest...> { static constexpr int id=7; };
template<class T,class... Rest> struct Many<T **, Rest...> { using id=long; };
template<class T,int N> struct Numbered { static constexpr int id=0; };
template<int N> struct Numbered<int *,N> { using id=short; };
int packed() { return sizeof(Many<int *, char>::id) + sizeof(Many<int **, char, double>::id) + sizeof(Numbered<int *, 4>::id); }
template<class T> struct Container { template<class> class Element {}; };
template<class T> struct FriendToMember { friend class Container<T>::template Element<int>; };
