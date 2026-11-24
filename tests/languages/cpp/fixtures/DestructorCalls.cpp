namespace library { struct Cell {}; }
template<class T> void retire(T *p) { p->T::~T(); }
using Count = int;
void end_count(Count &value) { value.Count::~Count(); }
void end_cell(library::Cell *p) { p->library::Cell::~Cell(); }
template<class T> struct Box {};
void end_box(Box<int> &box) { box.Box<int>::~Box<int>(); }
template<class T> void nested(T *p) { p->T::Inner::~Inner(); }
void absolute(library::Cell &c) { (c.::library::Cell::~Cell)(); }
namespace library { template<class T> struct Handle {}; }
void release(library::Handle<int> *h) { h->library::Handle<int>::~Handle<int>(); }
