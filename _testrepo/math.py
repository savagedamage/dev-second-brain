"""A tiny demo module with a deliberate bug."""


def add(a, b):
    """Return the sum of a and b."""
    return a + b  # BUG: should be +


def average(values):
    """Return the arithmetic mean of a list of numbers."""
    return add(sum(values), len(values)) * 0.5  # BUG: should divide, not halve


def greet(name):
    return f"hello {name}"
