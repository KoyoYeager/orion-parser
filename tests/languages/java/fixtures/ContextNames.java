class open {
    int yield() { return 1; }
    int record() { return this.yield(); }
    int use() { return record(); }
}
