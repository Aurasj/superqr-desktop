import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "superqr-protocol"))
from protocol.colorgrid8.macrochroma import (
    gf_mul, gf_inv, gf_add, GF_EXP, GF_LOG,
    MacrochromaTile, generate_spatial_parity_tiles, TILE_PAYLOAD_BYTES
)
import random

k = 300
m = 20

# Test Gaussian elimination with full available parity pool (P >= N)
failed_count = 0
for trial in range(1000):
    num_missing = 10
    missing = random.sample(range(k), num_missing)
    num_avail_p = 15 # e.g. 5 parities missing, 15 available for 10 missing data
    avail_p = random.sample(range(m), num_avail_p)

    A = [[GF_EXP[((p + 1) * (idx + 1)) % 255] for idx in missing] for p in avail_p]

    # Gaussian elim on P x N matrix
    P = len(avail_p)
    N = len(missing)
    rank = 0
    for col in range(N):
        pivot = rank
        while pivot < P and A[pivot][col] == 0:
            pivot += 1
        if pivot == P:
            continue # Try next column
        A[rank], A[pivot] = A[pivot], A[rank]
        inv = gf_inv(A[rank][col])
        for j in range(col, N):
            A[rank][j] = gf_mul(A[rank][j], inv)
        for r in range(P):
            if r != rank and A[r][col] != 0:
                f = A[r][col]
                for j in range(col, N):
                    A[r][j] ^= gf_mul(f, A[rank][j])
        rank += 1

    if rank < N:
        failed_count += 1

print(f"Failed rank count in 1000 trials with pool selection: {failed_count}")
