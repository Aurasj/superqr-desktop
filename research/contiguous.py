import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "superqr-protocol"))
from protocol.colorgrid8.macrochroma import gf_mul, gf_inv, GF_EXP
import random

k = 300
m = 20

# Test: When data tiles are randomly missing, and parities are taken in available order (p0, p1, p2...)
# Vandermonde submatrix with contiguous parities (p=0..E-1)
singular_count = 0
for trial in range(5000):
    num_missing = random.randint(1, 20)
    missing = random.sample(range(k), num_missing)
    # Contiguous available parities p = 0 .. num_missing - 1
    avail_p = list(range(num_missing))

    A = [[GF_EXP[((p + 1) * (idx + 1)) % 255] for idx in missing] for p in avail_p]

    # Gaussian elim
    n = len(missing)
    singular = False
    for i in range(n):
        pivot = i
        while pivot < n and A[pivot][i] == 0:
            pivot += 1
        if pivot == n:
            singular = True
            break
        A[i], A[pivot] = A[pivot], A[i]
        inv = gf_inv(A[i][i])
        for j in range(i, n):
            A[i][j] = gf_mul(A[i][j], inv)
        for r in range(n):
            if r != i and A[r][i] != 0:
                f = A[r][i]
                for j in range(i, n):
                    A[r][j] ^= gf_mul(f, A[i][j])
    if singular:
        singular_count += 1

print(f"Singular count with contiguous parities in 5000 trials: {singular_count}")
