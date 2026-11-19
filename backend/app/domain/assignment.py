"""Minimum-cost assignment (the Hungarian / Kuhn-Munkres algorithm).

Given a cost matrix (rows = requests, columns = technicians, None = impossible),
find the set of (row, column) pairs, at most one per row and per column, that
assigns as many rows as possible at the lowest total cost. Runs in O(n³) for
n = max(rows, columns), which is instant for the dozens of requests and techs in
one service area.

Implementation: the classic shortest-augmenting-path version with row/column
potentials, on a square matrix padded with dummy rows/columns.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

# Large enough to never be chosen over a real pair, small enough to keep floats exact.
_IMPOSSIBLE = 1e9


def min_cost_assignment(cost: Sequence[Sequence[float | None]]) -> list[tuple[int, int]]:
    rows = len(cost)
    cols = max((len(r) for r in cost), default=0)
    if rows == 0 or cols == 0:
        return []
    n = max(rows, cols)
    # Shift costs so they're non-negative (the algorithm is exact for any reals, but
    # this keeps the impossible marker clearly larger than every real cost).
    finite = [c for row in cost for c in row if c is not None]
    if not finite:
        return []
    shift = -min(finite) if min(finite) < 0 else 0.0
    top = max(finite) + shift
    # Leaving a request unassigned (a dummy column) costs more than any real pair, so as
    # many requests as possible get a tech; an impossible pair costs more than that.
    unassigned = _IMPOSSIBLE + top
    impossible = 2 * _IMPOSSIBLE + top

    def at(i: int, j: int) -> float:
        if i >= rows:
            return 0.0  # dummy row: a tech left idle costs nothing
        if j >= cols:
            return unassigned
        if j >= len(cost[i]):
            return impossible
        c = cost[i][j]
        return impossible if c is None else c + shift

    # u, v: potentials; p[j]: row matched to column j (1-based, 0 = none).
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [math.inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = math.inf
            j1 = 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = at(i0 - 1, j - 1) - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    pairs: list[tuple[int, int]] = []
    for j in range(1, n + 1):
        i = p[j] - 1
        col = j - 1
        if i < rows and col < len(cost[i]) and cost[i][col] is not None:
            pairs.append((i, col))
    return sorted(pairs)
