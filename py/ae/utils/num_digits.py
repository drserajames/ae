"""
ae.utils.num_digits — number of decimal digits in a positive integer.
"""
import math

def num_digits(value: int):
    """Number of decimal digits in `value` (e.g. 512 → 3)."""
    return int(math.log10(value)) + 1
