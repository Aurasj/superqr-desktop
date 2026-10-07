import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "superqr-protocol"))
from protocol.colorgrid8.macrochroma import gf_mul, gf_inv, GF_EXP, GF_LOG
import random

# For K=300 data tiles, split into 2 blocks of 150 (Even/Odd tiles: block 0 = even indices 0..298, block 1 = odd indices 1..299)
# In each block of 150, we have 10 parities.
# Cauchy matrix for block:
# X = {p: p in 0..9}
# Y = {i: 16 + i for i in 0..149}
# A[p, i] = gf_inv(p ^ (16 + i))
# This is a 100% PROVABLY MDS Cauchy Reed-Solomon code! Every single submatrix has det != 0!

singular_cauchy = 0
for trial in range(10000):
    # Up to 10 missing in block
    num_missing = random.randint(1, 10)
    missing = random.sample(range(150), num_missing)
    num_p = random.randint(num_missing, 10)
    avail_p = random.sample(range(10), num_p)[:num_missing]

    A = [[gf_inv(p ^ (16 + idx)) for idx in missing] for p in avail_p]

    n = num_missing
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
        singular_cauchy += 1

print(f"Cauchy MDS Singular count in 10000 trials: {singular_cauchy}")
