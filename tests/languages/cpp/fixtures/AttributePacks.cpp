template<class... T> struct [[vendor::types(T)...]] Pack {};
template<class... T> struct [[vendor::marker, vendor::types(T)...]] Group {};
