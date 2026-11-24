void *operator new(unsigned long, void *address) noexcept;
void allocate(int n, void *address) {
    new int;
    ::new int(3);
    new int[n][2]{};
    new int[]{1, 2};
    new (int*)();
    ::new (address) (int){4};
    new (address) int(n);
    new int*[n];
    new (int[3]);
}
