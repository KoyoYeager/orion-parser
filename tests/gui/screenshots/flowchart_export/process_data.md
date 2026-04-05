graph LR
    n1["process_data(items, threshold=0)"]
    n2["output = []"]
    n3["error_count = 0"]
    n4["for item in items"]
    n5["not validate(item)"]
    n8["error_count += 1"]
    n9["continue"]
    n11["transformed = transform(item)"]
    n12["transformed >= threshold"]
    n15["output.append(transformed)"]
    n17["for item in items"]
    n18["error_count > 0"]
    n21["print('f'Skipped {error_...')"]
    n23["return output"]
    n24["END"]
    n1 --> n2
    n2 --> n3
    n3 --> n4
    n4 --> n5
    n5 --> n8
    n5 --> n11
    n8 --> n9
    n9 --> n11
    n11 --> n12
    n12 --> n15
    n12 --> n17
    n15 --> n17
    n17 --> n18
    n18 --> n21
    n18 --> n23
    n21 --> n23
    n23 --> n24