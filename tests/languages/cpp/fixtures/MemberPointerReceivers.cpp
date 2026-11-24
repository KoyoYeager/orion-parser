auto identity=[](auto x){return x;};
using F=decltype(identity);
struct Owner{F f;};
int read(Owner &o, F Owner::*pm){return (o.*pm).operator()<int>(1);}
using Data = F Owner::*;
int pointer(Owner *o, Data pm){return (o->*pm).operator()<long>(2);}
struct Derived : Owner {};
int inherited(Derived &d, Data pm){return (d.*pm).operator()<int>(3);}
struct Factory { F &get(int){return identity;} };
using Method = F &(Factory::*)(int);
int result(Factory *f,Method pm){return (f->*pm)(4).operator()<int>(5);}
int copied(Owner &o, Data pm){auto saved=pm; return (o.*saved).operator()<int>(6);}
int indexed(Owner &o, Data *members){return (o.*members[0]).operator()<int>(7);}
struct ArrayOwner { F values[2]; };
int array(ArrayOwner &o,F (ArrayOwner::*pm)[2]){return (o.*pm)[1].operator()<int>(8);}
struct Proxy { F *operator->*(int){return &identity;} };
int overloaded(Proxy p){return (p->*1)->operator()<int>(9);}
int direct(Owner &o){return (o.*&Owner::f).operator()<int>(10);}
int via_method(Factory *f){auto pm=&Factory::get; return (f->*pm)(1).operator()<int>(11);}
int inherited_address(Owner &o){auto pm=&Derived::f; return (o.*pm).operator()<int>(12);}
struct Globals { static F closure; };
F Globals::closure = identity;
int from_static(){auto p=&Globals::closure; return p->operator()<int>(13);}
using Trailing = auto (Factory::*)(F item) -> decltype(item);
int trailing(Factory &o,Trailing pm){return (o.*pm)(identity).operator()<int>(14);}
using Signature = F(int);
using FromSignature = Signature Factory::*;
int from_alias(Factory &f, FromSignature pm){return (f.*pm)(0).operator()<int>(15);}
using Callback = Signature *;
struct Callbacks { Callback handler; };
int slot(Callbacks *c, Callback Callbacks::*pm){return (c->*pm)(0).operator()<int>(16);}
template<class T> struct Box { F slot; };
using Specialized = F Box<int>::*;
int specialization(Box<int> &b,Specialized pm){return (b.*pm).operator()<int>(17);}
int specialized_address(Box<int> &b){auto pm=&Box<int>::slot; return (b.*pm).operator()<int>(18);}
