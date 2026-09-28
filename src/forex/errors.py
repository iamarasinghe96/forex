"""Operator-facing failures with an explicit recovery action."""


class OperatorError(RuntimeError):
    """A safe failure whose message tells the operator how to recover."""
