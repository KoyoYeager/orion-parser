template<class T, class U>
using Rebound = typename T::template rebind<U>::type;

template<class T>
auto read(const T& obj) -> typename T::value_type {
    return obj.template get<typename T::value_type>();
}
template<class T>
auto indirect(T* ptr) -> typename T::value_type {
    return ptr->template get<typename T::value_type>();
}
template<class T>
int call_static() { return T::template convert<int>(1); }
template<class T, class U>
using Direct = typename T::template rebind<U>;
