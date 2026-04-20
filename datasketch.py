"""Local fallback for the optional datasketch dependency."""


class MinHash:
    def __init__(self, num_perm=128):
        self.num_perm = num_perm
        self._tokens = set()

    def update(self, value):
        self._tokens.add(value)
