package fixtures;

class TextValues {
    static String escapes = """
        \b\t\n\f\r\"\'\\\377
        """;
    static String quotes = """
        raw "" and \""" keep going""";
    static String empty = """
        """;
    static String spaces = """
        \s
          indented\s
        """;
}
