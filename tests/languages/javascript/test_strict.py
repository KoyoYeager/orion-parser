import pytest

from orionparser.languages.javascript.pipeline import JavaScriptPipeline


@pytest.mark.parametrize("source", [
    '"use strict"; eval = 1', '"foo";"use strict";({arguments=0}=obj)',
    'function f(x,x){"use strict";}', 'function f([x]){"use strict";}',
    'function eval(){"use strict";}', 'function f(){"use strict"; function g(){yield}}',
    r'''function f(){'\1'; 'use strict';}''',
    '({m(){ "use strict"; delete x }})', '"use strict"; for(var x=1 in obj);',
    '"use strict"; let {yield} = obj;',
])
def test_strict_errors(source):
    with pytest.raises(ValueError):
        JavaScriptPipeline().parse(source)


@pytest.mark.parametrize("source", [
    '("use strict"); eval=1', r'"use\x20strict"; arguments=1',
    'function f(){"use strict"} eval=1',
    '({[eval=1](){ "use strict"; }})', '"use strict"; await;',
    '"use strict"; obj.yield; ({yield: 1});',
])
def test_scope_and_directive_spelling(source):
    assert JavaScriptPipeline().parse(source)["body"]
