package fixtures;

import java.util.List;
import java.io.IOException;
import java.lang.annotation.*;

@Target({ElementType.TYPE_USE, ElementType.TYPE_PARAMETER})
@interface A { String value() default ""; }
@Target({ElementType.TYPE_USE, ElementType.TYPE_PARAMETER})
@interface B {}

class Annotated<@A T extends @B Number & Comparable<@A T>>
        extends @A Object implements java.io.@B Serializable {
    java.lang.@A("segment") String @A("type") [] names @A("variable") [];
    List<@A ? super @B String> values;
    T f(T @A [] input @B []) @A [] throws @B IOException {
        List<@A String> @B [] xs = null;
        return (@A T @B []) null;
    }
    void spread(String @B ... values) {}
    Object make(int n) { Object x = new @A int[n]; return new @B String(); }
    boolean matches(Object obj) { return obj instanceof @A String; }
    int convert(long x) { return (@A int) -x; }
    class Member<U> {}
    Annotated<T>.@A Member<String> nested;
    int @B [] counters;
    boolean ready;
    <U> @A U result(U value) { return value; }
    List<String> fresh() { return new java.util.@A ArrayList<>(); }
}
