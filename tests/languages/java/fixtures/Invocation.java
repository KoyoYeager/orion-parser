package fixtures;

import java.lang.annotation.ElementType;
import java.lang.annotation.Target;

class Invocation {
    @Target(ElementType.TYPE_USE)
    @interface Mark {}
    <T> Invocation(T value) {}
    Invocation() { <Integer>this(1); }
    static <T> T identity(T value) { return value; }

    class Parent {
        int flag = 1;
        <T> Parent(T value) { super(); }
        <T> T id(T value) { return value; }
    }
    class Child extends Parent {
        Child(@Mark Invocation Invocation.this, Invocation owner) { owner.<String>super("init"); }
        String apply(@Mark Child this, Child other) {
            String s = Invocation.<String>identity("value");
            s = other.<String>id(s);
            s = (this).<String>id(s);
            return super.<String>id(s);
        }
        class Nested {
            Child owner() { return Child.this; }
            int flag() { return Child.super.flag; }
            String read() { return Child.super.<String>id("x"); }
        }
        int ownFlag() { return super.flag; }
    }
    class Grand extends Child {
        Grand(Invocation owner) { (owner).super(owner); }
    }
}
