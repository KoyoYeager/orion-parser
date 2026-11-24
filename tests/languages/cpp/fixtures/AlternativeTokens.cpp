bool compare(int a, int b) <%
    int values<:2:> = <%a, b%>;
    a and_eq values<:1:>;
    a or_eq b;
    a xor_eq 1;
    return not (a not_eq b) or ((a bitand b) and (compl a bitor (a xor b)));
%>
