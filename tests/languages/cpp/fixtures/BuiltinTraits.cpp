template<class T, class U, class... Args>
struct Traits {
    enum {
        trivially_copyable = __is_trivially_copyable(T),
        array = __is_array(T), bounded = __is_bounded_array(T), function = __is_function(T),
        member_method = __is_member_function_pointer(T), member_object = __is_member_object_pointer(T),
        member_pointer = __is_member_pointer(T), object = __is_object(T),
        reference = __is_reference(T), trivial_ctor = __has_trivial_constructor(T), convertible = __is_convertible(T, U),
        an_enum = __is_enum(T), a_union = __is_union(T), a_class = __is_class(T),
        abstract = __is_abstract(T), aggregate = __is_aggregate(T), empty = __is_empty(T),
        final_class = __is_final(T), literal = __is_literal_type(T), pod = __is_pod(T),
        polymorphic = __is_polymorphic(T), standard_layout = __is_standard_layout(T),
        trivial = __is_trivial(T), trivial_destructor = __has_trivial_destructor(T),
        virtual_destructor = __has_virtual_destructor(T), unique = __has_unique_object_representations(T),
        assignable = __is_assignable(T &, U), nothrow_assign = __is_nothrow_assignable(T &, U),
        trivial_assign = __is_trivially_assignable(T &, U), base = __is_base_of(T, U),
        same = __is_same(T *, U *), default_construct = __is_constructible(T),
        construct = __is_constructible(T, Args...), trivial_construct = __is_trivially_constructible(T, U),
        nothrow_construct = __is_nothrow_constructible(T, U, int)
    };
};
