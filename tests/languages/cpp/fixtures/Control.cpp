int select(int n) {
    do {
        switch (n) {
        case 1: goto done;
        default: --n; break;
        }
    } while (n > 0);
done:
    return n;
}

using Finish = long;
int skip(int n) {
    while (n > 0) {
        if (--n) continue;
        goto Finish;
    }
Finish:
    return sizeof(Finish) + n;
}
