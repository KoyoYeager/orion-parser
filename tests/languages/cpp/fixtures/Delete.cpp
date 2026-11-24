void release(int *one, int *many, int **slots) {
    delete one;
    ::delete [] many;
    delete[] slots[0];
    ::delete (int*)slots[1];
}
