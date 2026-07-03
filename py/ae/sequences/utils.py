"""
ae.sequences.utils — small sequence helpers.
"""

def hamming_distance(seq1: str, seq2: str) -> int:
    """Number of positions at which `seq1` and `seq2` differ (compared over the length of
    `seq1`)."""
    dist = 0
    for i, nuc in enumerate(seq1):
        if nuc != seq2[i]:
            dist += 1
    return dist

# ======================================================================
