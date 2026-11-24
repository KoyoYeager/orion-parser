struct Cell { int value; };
using Pointer = int * [[example::inner]] const * [[example::outer]];
using Member = int Cell::* [[example::member]] volatile;
using Ref = int & [[example::reference]];
using Move = int && [[example::move]];
using Callback = int (* [[example::callback(1, [2])]])(int);
void visit(int (* [[example::handler]] callback)(int), int (& [[example::array]] values)[3]);
template<class T> struct Box { int field; };
using Templated = int Box<int>::* [[example::element]];
struct Qualified {
    auto inspect() const bitand noexcept [[example::method]] -> int;
    Qualified() noexcept [[example::ctor]];
    ~Qualified() [[example::dtor]];
    int consume() and [[example::method]];
    operator bool() const & [[example::convert]];
};
using Method = int (Qualified::* [[example::ptr]])() const && noexcept [[example::signature]];
