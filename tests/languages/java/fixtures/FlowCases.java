package fixtures.coverage;

class FlowCases {
    int walk(@Deprecated final int[] data, int index, boolean a, boolean b) {
        ;
        { index++; }
        if (a) ++index;
        if (a) if (b) index++; else index--; else --index;
        if (a) stop: while (b) { break stop; } else index++;
        if (a) while (b) index--; else ++index;
        if (a) for (index = 0, index += 1; index < data.length; index++) {} else index--;
        if (a) for (int item : data) index += item; else --index;
        do { --index; } while (index > 0);
        assert a;
        if (b) throw new IllegalArgumentException();
        new String();
        touch();
        var current = index;
        return current;
    }
    void touch() { return; }
}
