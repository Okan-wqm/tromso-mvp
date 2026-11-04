"""The seeded deal of an experiment's tanks to its replicates, pure (no database). The method is named and its name
stored with the seed (`Experiment.allocation_method`), so the same pool and seed give the same placements for ever,
whatever Python version or machine runs it.

`sha256_v1`: each item of the pool is given the key SHA-256 of "<seed>:<code>" (its code: a tank's or a system's, which
the caller makes unique), the items are sorted by that key, and the item at place i takes the i-th slot, the slots
being the replicates in the order of their group's position and their number. It is not `random.shuffle(seed)`: only
`random.random()` is guaranteed to give the same numbers in every Python version, while a hash is fixed by its standard.
The arrangement depends on nothing but the pool and the seed the person chose and wrote down, so a reviewer can
repeat it.
"""
import hashlib

METHOD = 'sha256_v1'


def sort_key(seed, code):
    """The key an item is sorted by: the SHA-256 of "<seed>:<code>", as hexadecimal text (sorted as text)."""
    return hashlib.sha256(f'{seed}:{code}'.encode()).hexdigest()


def deal(codes, slots, seed):
    """[(slot, code)] in the order of the slots: `codes` (the items of the pool) sorted by their keys under `seed`,
    the i-th taking the i-th of `slots` (already in their order). Equal numbers are the caller's to check."""
    ordered = sorted(codes, key=lambda code: (sort_key(seed, code), code))
    return list(zip(slots, ordered))
