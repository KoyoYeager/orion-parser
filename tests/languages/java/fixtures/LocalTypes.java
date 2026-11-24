package fixtures;

class LocalTypes {
    Object make(int record) {
        final int value = record;
        @Deprecated abstract class Base { abstract int get(); }
        final class Child extends Base { int get() { return value; } }
        interface Tag {}
        enum Choice { YES, NO }
        record Box(int value) implements Tag {}
        return new Box(new Child().get());
    }
}
