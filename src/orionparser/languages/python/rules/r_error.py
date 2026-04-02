"""Error recovery rules.

PLY's built-in error recovery handles token discarding.
The `error` token in grammar rules (p_statement_error) catches
and recovers from syntax errors at the statement level.
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
    p[0] = {"type": "ErrorNode", "_line": p.lineno(1)}
