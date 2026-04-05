graph TD
    _module_["<module>"]
    main["main"]
    parse_file["parse_file"]
    validate["validate"]
    read_tokens["read_tokens"]
    Config___init__["Config.__init__"]
    _module_ --> main
    _module_ --> Config___init__
    main --> parse_file
    main --> validate
    parse_file --> read_tokens