package fixtures.coverage;

@Deprecated
public abstract strictfp class Declarations {
    @Deprecated public static final int LIMIT = 1 + 2;
    protected transient long saved;
    private volatile char code;
    byte small;
    short medium;
    double large;
    float fraction;
    boolean ready;
    { ready = false; }
    static { System.nanoTime(); }

    @Deprecated protected Declarations() {}
    private Declarations(int value) { this(); }
    public <T> Declarations(T value) { this(); }

    @Deprecated protected abstract void hook();
    private static native int nativeCall(long value);
    public final synchronized strictfp float ratio(float f) { return f; }
    <E extends Exception> void raise(E error) throws E { throw error; }

    protected static abstract class Base {}
    private static final class Final {}
    @Deprecated public abstract static strictfp interface Api extends Runnable, AutoCloseable {
        @Deprecated public static final int NUMBER = LIMIT;
        public abstract void run();
        @Deprecated default strictfp void close() { helper(); }
        private void helper() {}
        static int number() { return NUMBER; }
        class Nested {}
        interface Service {}
        ;
    }
    protected interface Protected {}
    private interface Private {}
    sealed interface Closed permits Open {}
    non-sealed interface Open extends Closed {}
    ;
}
