extern "C" int external_c(int);
extern "C++" {
    using Count = int;
    extern "C" Count inside(Count value) { return value + 1; }
}
extern "C++" {}
Count use_linkage(Count n) { return external_c(n) + inside(n); }
extern "C++" __attribute__((__noreturn__)) void halt();
extern "C++" void stop() noexcept __attribute__((__noreturn__, __cold__));
extern "C" "++" int combined();
extern "C" ;
typedef __decltype(0) ImplementationInt;
extern R"lang(C++)lang" int raw_linkage();
