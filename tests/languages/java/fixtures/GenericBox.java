package fixtures;

import java.util.List;
import java.util.Map;

class GenericBox<T extends Number & Comparable<T>> extends Object implements java.io.Serializable {
    Map<String, List<? extends T>> sources;
    List<Map<String, List<? super T>>> sinks;

    GenericBox() { super(); }
    <U extends T> GenericBox(U value) { this(); }

    <R> R identity(R value) { return value; }
    GenericBox<T> copy() { return new GenericBox<>(); }
    GenericBox<T> explicit() { return new GenericBox<T>(); }
    int shift(int a, int b) { return a < b >> 2 ? a >>> 1 : b; }
}
