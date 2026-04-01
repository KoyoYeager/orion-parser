"""Error recovery rules.

Follows the reference C parser's panic mode approach:
synchronize on NEWLINE + DEDENT tokens.
"""

import logging

logger = logging.getLogger(__name__)


def p_error(p):
    if p is None:
        logger.debug("Syntax error: unexpected end of file")
        return
    logger.debug("Syntax error at line %d: unexpected %s (%r)", p.lineno, p.type, p.value)


def p_statement_error(p):
    """statement : error NEWLINE"""
    logger.debug("Recovered from error at line %d", p.lineno(1))
    p[0] = {"type": "ErrorNode", "line": p.lineno(1)}
