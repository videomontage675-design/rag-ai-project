"""Phase 3 PoC: exact vector search inside SQLite at the SRS capacity target.

Compares two single-file, transactional designs (metadata and vectors in one
SQLite database, so deletes and version switches are atomic):

  A. SQLite stores vectors as BLOBs; NumPy computes exact cosine similarity
     over the active rows (selected by SQL first, so filtering is exact).
  B. sqlite-vec 0.1.9 vec0 virtual table with a metadata column for the
     active flag, queried with KNN + WHERE active = 1.

Scale: NFR-PRF-05 (20,000 chunks), 30% of rows inactive (older document
versions, FR-VER-02). Reports per-query latency and agreement of B with the
exact ground truth from A. Absolute timings depend on the CPU; the comparison
between A and B on the same machine is what matters.

Usage (from poc/storage):  .venv/bin/python bench_vector_search.py
"""
import sqlite3, time, statistics
import numpy as np
import sqlite_vec

N, K, QUERIES, INACTIVE = 20_000, 10, 50, 0.30
rng = np.random.default_rng(42)

def run(dim: int) -> None:
    vecs = rng.standard_normal((N, dim)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    active = rng.random(N) >= INACTIVE
    queries = rng.standard_normal((QUERIES, dim)).astype(np.float32)
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)

    db = sqlite3.connect(":memory:")
    db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
    db.execute("CREATE TABLE chunk(id INTEGER PRIMARY KEY, active INTEGER, emb BLOB)")
    db.execute(f"CREATE VIRTUAL TABLE vec USING vec0(id INTEGER PRIMARY KEY, active INTEGER, emb float[{dim}] distance_metric=cosine)")
    with db:
        db.executemany("INSERT INTO chunk VALUES (?,?,?)", ((i, int(a), v.tobytes()) for i, (a, v) in enumerate(zip(active, vecs))))
        db.executemany("INSERT INTO vec(id, active, emb) VALUES (?,?,?)", ((i, int(a), v.tobytes()) for i, (a, v) in enumerate(zip(active, vecs))))

    # A: load active vectors once (a real system caches this and refreshes on change)
    t0 = time.perf_counter()
    rows = db.execute("SELECT id, emb FROM chunk WHERE active = 1").fetchall()
    ids = np.array([r[0] for r in rows]); mat = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), dim)
    load_ms = (time.perf_counter() - t0) * 1000
    a_times, truth = [], []
    for q in queries:
        t0 = time.perf_counter()
        sims = mat @ q
        top = np.argpartition(-sims, K)[:K]; top = top[np.argsort(-sims[top])]
        a_times.append((time.perf_counter() - t0) * 1000); truth.append(list(ids[top]))

    b_times, agree, short = [], [], 0
    for q, t in zip(queries, truth):
        t0 = time.perf_counter()
        res = db.execute("SELECT id FROM vec WHERE emb MATCH ? AND k = ? AND active = 1 ORDER BY distance", (q.tobytes(), K)).fetchall()
        b_times.append((time.perf_counter() - t0) * 1000)
        got = [r[0] for r in res]; short += len(got) < K
        agree.append(len(set(got) & set(t)) / K)

    print(f"| {dim} | A: NumPy exact | {statistics.median(a_times):.2f} ms | load active vectors once: {load_ms:.0f} ms | exact (ground truth) |")
    print(f"| {dim} | B: sqlite-vec 0.1.9 | {statistics.median(b_times):.2f} ms | none | top-{K} agreement {100*statistics.mean(agree):.1f}%, short results {short}/{QUERIES} |")

print(f"N={N}, k={K}, inactive={int(INACTIVE*100)}%, queries={QUERIES}, sqlite {sqlite3.sqlite_version}")
print("| Dim | Design | Median query latency | Startup cost | Correctness |\n|---|---|---|---|---|")
for d in (768, 1024, 3072):
    run(d)
