package fixtures;

import java.util.List;
import java.util.function.*;

class Functional<T> {
    Function<T,T> identity = v -> v;
    BiFunction<T,T,T> choose = (a,b) -> a;
    Consumer<String> print = (final String s) -> { System.out.println(s); };
    Function<String,String> withVar = (@Deprecated var s) -> s;
    Action varargs = (String... xs) -> { use(xs); };
    Supplier<String> build = String::new;
    Supplier<List<T>> nested = java.util.ArrayList<T>::new;
    IntFunction<String[]> array = String[]::new;
    Function<T,String> viaName = String::valueOf;
    Supplier<String> viaReceiver = this::toString;
    Supplier<String> viaSuper = super::toString;
    Function<List<T>,Integer> viaType = List<T>::size;
    Function<T,T> explicit = this::<T>copy;
    Function<T,T> cast = (Function<T,T> & java.io.Serializable) x -> x;
    Function<T,T> branch = enabled() ? x -> x : x -> copy(x);
    class Inner { Supplier<String> outer = Functional.super::toString; }

    interface Action { void accept(String... xs); }
    void use(String[] xs) {}
    <U> U copy(U value) { return value; }
    boolean enabled() { return true; }
    int primitiveCast(long n) { return (int) -n; }
    T referenceCast(Object value) { return (T) value; }
}
