### [DONE] PROMPT-003 Audit Phase 9 — Performance Profiling, Infrastructure & Operational Consistency Audit

- **Prompt**: SESSION-B-KICKOFF.md (subagent W1-C)
- **Session date**: 2026-09-30
- **Assigned subsystem**: capture + detection performance, PowerShell ops lifecycle, Docker topology, documentation drift, dead code
- **Method**:
  - **Profilers used**: `cProfile` (sorted by `tottime`) for `run_detection()` and `layer4_visual_diff()`; `pstats`; `time.perf_counter` with `statistics.median` and explicit **n ≥ 3** for every number; `EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)`; `docker info --format json` / `docker stats`; isolated PowerShell harnesses for the script logic; a fixture-driven AST/source cross-check for the documentation sweep.
  - **Environment**: AMD Ryzen 5 5625U, 6C/12T, 15.34 GB total RAM, 4.46 GB free at probe time. Docker Desktop ceiling **7 976 714 240 B = 7.43 GiB** (`docker info` → `MemTotal`; `NCPU` 12). Live stack healthy throughout. Scratch DB `wardress_w1c_test` on `wardress-test-pg` `127.0.0.1:5433`, created and **dropped** by me.
  - **⚠️ CONTENTION CAVEAT (mandatory reading for every number below).** Two sibling Wave-1 subagents (W1-A stress catalog, W1-B detection accuracy) were running concurrently and consuming CPU/RAM for the whole session. **Every timing in this report is contention-affected and is NOT a clean-machine number.** They are stated as *relative* comparisons (A vs B measured interleaved in the same process, same conditions) wherever a decision depends on them, which is the only form in which they are decision-grade. The absolute DB round-trip floor (87–180 ms) is *entirely* Python/asyncpg/uv startup overhead, not query time, and is a clean statement of the per-task cost. **A clean re-measurement should be run after Wave 1 finishes**; the coordinator should treat §1 as directional.
  - **Rule 1 attestation**: **zero** modifications to tracked production files. `git status --short` shows only the coordinator's `PROMPT-003-IMPLEMENTATION-LOG.md` modification, Session A's + W1-A's scratch/test files, and nothing of mine. All scratch lives in `C:\Users\Ns8pc\AppData\Local\Temp\opencode\w1c\`. No temporary instrumentation was left in the repo; no test files were added (see §10).
  - **Live stack etiquette**: the shared stack was only ever *read* (`docker compose ps`, `docker info`, HTTP GETs to `/openapi.json`, `/docs`, `/redoc`, `/docs/oauth2-redirect`, `/api/health*`, and SELECTs against `wardress-db-1`). No container stopped, restarted, rebuilt or recreated. Live DB verified unchanged at the end (`sites=0 scans=0 baselines=0 alerts=0 users=1 apikeys=0 channels=0 suppression=0 hooks=0`).

### Explicit note on the Rule 15 conflict — what I could NOT run live, and how I substituted

**Rule 15 of the audit spec is absolute: "Do not run `scripts/install.ps1` or `scripts/uninstall.ps1` yourself."** The Session-B kickoff's backup/restore request was explicitly conditional ("*If possible*, run full `uninstall.ps1` backup → fresh install → `RESTORE.txt` replay"). It is **not possible**: running `uninstall.ps1` would execute `docker compose --profile telegram --profile ollama down -v --rmi local` and destroy the live `wardress_db-data`, `wardress_redis-data` and `wardress_scan-artifacts` volumes that two sibling subagents are actively testing against. **I did not run it, and Rule 15 wins over the kickoff's soft phrasing.**

**Substitutions used, all within the rules:**

| What the brief asked for | What I did instead | Confidence |
|---|---|---|
| `uninstall.ps1` backup → install → `RESTORE.txt` replay | **Full static analysis** of the backup path (`uninstall.ps1:113-338`) and the restore contract it emits, plus a **bidirectional artifact-coverage cross-check** (§8, OPS-5) | **Medium-high** on the static conclusions; the *end-to-end replay remains UNVERIFIED* and a live run would still be needed to confirm the `pg_dump` byte-exactness and the `docker run -v` mount quoting |
| Run `update.ps1` to observe the `.env` merge | **Never ran it.** Static analysis found there is **no merge at all**; I then proved the operator-visible consequence on the **live `.env`** by diffing its key set against `.env.example` (read-only) | **High** |
| Run `install.ps1` to observe preflight | **Read-only analysis** of all 17 steps + cross-reference against the live environment | **High** on what it checks/doesn't check; the interactive path was not exercised |
| Test `diagnostics.ps1` secret scrubbing | Confirmed by reading that it is **non-mutating** w.r.t. the deployment, then tested the scrubbing functions **in isolation**: the two functions were copied **verbatim** into a scratch harness and pointed at a **synthetic** `.env` fixture. The real `.env` was never read and no live credential entered the harness or the report. | **High** — 16 hostile-shaped probes, 9 escaped |
| Verify `validate.ps1` thresholds | Replayed its exact arithmetic (`docker info --format json` → `MemTotal` → `[math]::Round(/1GB,1)` → `-lt 4`) against the live engine | **High** — it is 4 lines of arithmetic and I evaluated them |

**What this means for the coordinator:** every finding below is either a *code/doc fact* (certain) or a *static-analysis inference about operator behaviour* (labelled with a confidence level). Nothing in this report depends on having destroyed a working install.

---

## 1. Profiling results

### 1.1 The profiling table

All on the **host**, `uv run --frozen python` from `backend/`, AMD 5625U / 12 logical, **contention-affected** (see header). `n` = independent passes; `sd` = sample standard deviation.

| # | Measurement | Profiler | n | min | **median** | max | sd | Verdict |
|---|---|---|---|---|---|---|---|---|
| P1 | **MiniLM cold load** (`semantics._get_model`, warm HF cache) | `perf_counter` | 1 (cold is one-shot) | — | **19.86 s** | — | — | Host warm-cache figure. Coordinator's 54.71 s is the cold-HF-cache figure. **Both are per-child** (see §1.2) |
| P2 | MiniLM **warm single** `encode()` (500-char chunk) | `perf_counter` | 5 | 27.31 | **27.78 ms** | 28.38 | 0.45 | Tight (sd 1.6%). The per-call floor |
| P3 | **24 individual** `encode()` calls (= one layer-8 side, worst case) | `perf_counter` | 3 | 559.2 | **606.8 ms** | 618.3 | 32.7 | Session A measured 626.5 ms. **Corroborated** |
| P4 | **24 in one batched** `encode()` | `perf_counter` | 3 | 342.2 | **345.0 ms** | 356.1 | 7.4 | |
| P5 | **Batching payoff** (P3 − P4) | derived | 3 | — | **261.7 ms, 1.76×** | — | — | Session A measured 1.68× / −253 ms. **Corroborated** |
| P6 | `layer9_fusion()` cost | `perf_counter` over 2000 calls × 3 | 6000 | — | **0.0135 ms** | — | — | Negligible |
| P7 | Fusion **artifact reloads** during 6000 `layer9_fusion` calls | monkeypatched `json.loads` counter | 6000 | — | **0** | — | — | **INVALIDATES** the "fusion reload" bottleneck hypothesis. Cached once per process |
| P8 | Fusion artifact **cold** read+validate | `perf_counter` | 1 | — | **0.2985 ms** | — | — | One-time, irrelevant |
| P9 | Import of all 6 detection modules (first compile of every pattern) | `perf_counter`, `re._cache` purged first | 2 | 53.98 | **53.98 / 79.25 ms** | 79.25 | — | One-time. 119 patterns land in `re._cache` |
| P10 | `dom.py:212` inline `re.sub(r"\s+","")` per call (hot loop) | `perf_counter`, 2000 reps × 5 | 10 000 | 1.68 | **1.725 µs** | 1.77 | 0.049 | Served from `re`'s 512-entry cache. **NOT recompiled** |
| P11 | `signatures.py:115` inline `re.sub(r"<[^>]*>")` (DOM-fallback branch) | `perf_counter` | 5 | 0.0012 | **0.0019 ms** | 0.0755 | — | Only reached when lxml cannot parse |
| P12 | `signatures.py:108 extract_visible_text()`, 14 KB well-formed (lxml path) | `perf_counter` | 5 | — | **0.52 ms** | — | 0.153 | |
| P13 | `run_detection()` total, 14 KB benign churn, screenshots present | `perf_counter` | 5 | 45.96 | **51.5 ms** | 122.06 | 31.64 | |
| P14 | `run_detection()` total, 14 KB attack, screenshots present | `perf_counter` | 5 | 53.74 | **58.4 ms** | 66.62 | 6.10 | |
| P15 | **`layer8_semantics` share of `run_detection`** (per-layer wall clock wrapper) | instrumentation + `perf_counter` | 3 | — | **48.18 / 44.74 ms (93.5% / 93.1%)** | — | — | Session A measured 66% of a ~1.44 s cost. **Both correct at their own scale** — see §1.3 |
| P16 | `layer4_visual_diff`, 1280×4000 real PNGs | `perf_counter` | 5 | 998.4 | **1030.1 ms** | 1133.8 | 54.1 | |
| P17 | `layer4_visual_diff`, 1280×3000 real PNGs | `perf_counter` | 5 | 328.7 | **362.4 ms** | 401.2 | 63.4 | |
| P18 | `resize()` calls per layer-4 call | `PIL.Image.resize` monkeypatch counter | 5 runs | — | **8** (identical every run) | — | — | **Confirms Session A's count exactly** |
| P19 | `convert()` calls per layer-4 call | `PIL.Image.convert` counter | 5 runs | — | **8** in the full call, **6** excluding `_load_rgb`'s 2 | — | — | **Confirms Session A's 8+8** |
| P20 | Layer-4 A/B: **AS-IS** vs **"resize once"** proposal, 1280×3000 | interleaved A/B, `perf_counter` | 5+5 | 417.1 | 362.4 → **328.1** | 555.5 | 50–63 | +34.3 ms (9.5%) |
| P21 | Same A/B at 1280×4000 | interleaved A/B | 5+5 | 417.1 | 610.3 → **632.2** | 660.8 | 97–116 | **−21.9 ms (−3.6%) — the sign flips.** See §10 O-1 |
| P22 | Per-task DB engine: **fresh** per `task_session()` | `perf_counter` | 5 | 65.06 | **95.06 ms** | 180.57 | 40.4 | Session A measured 87.98 ms. **Corroborated** |
| P23 | Per-task DB engine: **warm pooled** checkout + `SELECT 1` | `perf_counter` | 5 | 4.76 | **5.32 ms** | 6.32 | 0.68 | Session A measured 6.59 ms. **Corroborated** |
| P24 | **Engine-build penalty** (P22 − P23) | derived | 5 | — | **89.74 ms, 17.9×** | — | — | Session A measured 81 ms / 13×. **Corroborated** |
| P25 | EXPLAIN client round trip, host loopback, `SELECT 1` under `NullPool` | `perf_counter` | 3 per query × 10 | 76.4 | **87.3–179.8 ms** | 206.3 | — | **This is Python + asyncpg + uv event-loop startup, not query time.** Postgres `Execution Time` for the same statements: **0.033–0.069 ms** |
| P26 | `worker/db.py::task_session` shapes | P22/P23 | — | — | **17.9× per Celery task** | — | — | ~2 400 tasks/day → ~215 s/day of pure overhead |
| P27 | Benign-churn fused-risk band, 6 variants, screenshots present | `run_detection` | 6 | 0.3000 | **0.3000** | 0.3000 | 0 | See §5 DOC-2 |
| P28 | **Poisoned** (200-OK wall anchor) fused risk | real task bodies, scratch DB | 1 (deterministic) | — | **0.9999999999997338** | — | — | `verdict = flagged`. See §4 |
| P29 | **Control** (healthy anchor, same page) fused risk | real task bodies, scratch DB | 1 (deterministic) | — | **0.3000** | — | — | `verdict = changed` |
| P30 | `normalized_copy()` ReDoS scope, 11 adversarial docs up to 1.95 MB | `perf_counter` | 11 | 1.40 | **7.95 ms** | **136.04 ms** | — | **0 exceptions raised.** See §5 DOC-5 |
| P31 | Suppression `regex` timeout, `(a\|aa)+b` on 800 KB of text | real `suppressed_copy` path | 1 | — | **2018.6 ms** | — | — | **The 2.0 s bound fires**, rule skipped with a warning |
| P32 | Suppression `regex` timeout, `(\w+\W+)*$` | real path | 1 | — | **2188.3 ms** | — | — | Bound fires |
| P33 | Six "classic bomb" patterns through the real suppression path | real path | 6 | 14.0 | **14.0–26.9 ms** | 26.9 | — | Defeated by `regex`'s optimiser, not by the timeout |

### 1.2 Cold-start embedding: who actually pays it, and how often

This is the question the brief asked and the answer is sharper than "54.71 s per scan".

**The parent does NOT load the model before fork — and that is the good half.** `worker/celery_app.py:15-20` uses Celery's `include=[...]`, which is resolved when the app is *finalised* — i.e. **in the parent, before `prefork` forks**. So `worker.scan_tasks` and its transitive `worker.detection.semantics` (and therefore `torch`, `transformers`, `lxml`, `skimage`) are all imported **once in the parent** and shared copy-on-write across every child. Session A's live cold pool of **1.32 GiB for 12 children** (not 12 × 234 MB) is the direct evidence of that sharing.

**The bad half: the weights are loaded lazily, in the child, once per child.** `semantics.py:131-137`:

```python
_model = None
def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
    return _model
```

There is **no lock, no `lru_cache`, and no pre-fork warm-up**. Consequences, all measured or traced:

- **Per child, not per task.** A warm child pays the 19.86 s / 54.71 s load exactly **once**, on its first layer-8 call, and never again. The worker's memory curve is therefore a **staircase**: 12 children each burn ~20–55 s of CPU on their *first* task, and because `task_prefetch_multiplier=1` (`celery_app.py:32`) those first tasks are staggered by however long each child takes to reach layer 8.
- **The load happens *inside* the scan's time budget.** `task_soft_time_limit=420`, `task_time_limit=480` (`celery_app.py:44-45`). A first-ever scan on a freshly-forked child therefore spends **4.4–11.4% of its entire 480 s hard limit just loading the model** before any detection begins. On a child that has run one task already, the cost is 0.
- **`_get_model()` has no lock.** Within one Celery child this is safe (a prefork child runs one task at a time), but it is a latent hazard the moment anything runs two coroutines per child. `worker/scan_tasks.py:238-260` is a single `asyncio.run()` per task, so today it cannot fire. **Not a finding — recorded so the remediation does not "fix" a non-bug.**
- **A model-load failure is silent.** `embed_text` catches every exception and returns `None` (`semantics.py:147-149`), so a child whose model never loads emits a `logger.warning` and contributes **48 zeroed layer-8 features** to fusion. Combined with `_UNMEASURED_RISK_CEIL`, that is a *lower*-risk scan, not a crash — benign by design, but it means "MiniLM unavailable" is a **log line, not a health signal**, and the health page has no surface for it.

**`--max-tasks-per-child` does not help.** Session A measured that freeing the model returns 0.2 MB of 624.5 MB, so a recycled child re-acquires the same 390 MB marginal footprint *and* re-pays the load. That is why the only real lever is pinning `-c` (Session A opportunity #12). I did not repeat the memory measurement; it is outside my contention budget and Session A's numbers are load-bearing and uncontested.

### 1.3 Where detection time actually goes, and how it scales

The brief's candidate "layer 8 is a large share" is **correct but scale-dependent**, and reporting it without the denominator would be misleading. Measured with a per-layer wall-clock wrapper, interleaved, 3 passes each:

| document size | `run_detection` total | **layer 8** | L8 share | next-cost layers (ms) |
|---|---|---|---|---|
| 0.3 KB | 86.8 ms | 95.1 ms\* | \*\* | L2 1.12 · L5 1.08 · L3 0.45 |
| 6 KB | 858.2 ms | 935.4 ms\* | \*\* | L2 7.23 · L5 4.35 · L3 2.24 |
| 27 KB | 2651.8 ms | 2478.0 ms | 93.4 % | L2 22.84 · L5 12.21 · L3 6.61 |
| 68 KB | 2579.0 ms | 2448.5 ms | 94.9 % | L2 45.14 · L5 24.46 · L3 11.01 |
| 171 KB | 2924.6 ms | 3005.1 ms\* | \*\* | L2 138.90 · L5 74.29 · L3 39.91 |

\* the L8-vs-total columns come from two separately-timed 3-pass loops, so at small sizes they disagree by more than the run-to-run sd; the absolute per-layer milliseconds are the reliable figure and the 27 KB and 68 KB rows are the internally-consistent ones.

**The structurally important result is the shape, not the ratio:**

- **Layer 8 SATURATES at ~2.4–3.0 s.** It is hard-capped by design: `_MAX_CHUNKS_PER_SIDE=24`, `_EMBED_CHUNK_CHARS=600`, `_EMBED_CHAR_CAP=5000` (`semantics.py:163-176`), so the worst case is **2 sides × 24 = 48 `encode()` calls ≈ 1.3 s** at P3's rate, plus `_direction_similarity`'s O(24×24)=576 cosine computations over 384-dim vectors. It cannot get more expensive no matter how large the page is.
- **Layers 2, 5 and 3 grow LINEARLY and WITHOUT BOUND**: L2 1.12 → 7.23 → 22.84 → 45.14 → **138.90 ms** across 0.3 KB → 171 KB, i.e. ≈ **0.8 ms/KB**. Extrapolated (stated as extrapolation, Rule 12): a 2 MB single-page app — entirely plausible for a modern SPA — puts L2 alone at **~1.6 s** and L2+L3+L5 at **~2.5 s**, which is *more* than the entire saturated layer 8.
- **So the honest statement is: layer 8 dominates *today* (93–95% of a normal page's detection cost) and is the one cost that is already bounded; layers 2/3/5 are the costs that will dominate as pages grow, and they are the ones nobody has measured.** Session A's 66% figure was measured on a ~1.44 s total, consistent with a larger page where L2/L3/L5 have grown relative to a saturated L8.
- **cProfile, `run_detection` × 3 (attack case), tottime — 84 904 function calls in 0.213 s** confirms the shape: `torch._C._nn.linear` 0.076 s (36 % of all time, 222 calls), `scaled_dot_product_attention` 0.010 s, `lxml.html.document_fromstring` 0.010 s (36 calls), `torch.nn.Module._apply` 0.008 s, `torch._C._nn.gelu` 0.005 s. `worker/detection/signatures.py:110 extract_visible_text` is only 0.002 s. **There is no Python-level hotspot anywhere** — the cost is torch kernels and lxml parsing, i.e. irreducible without changing the models or the parser.
- **cProfile, `layer4_visual_diff` × 3, tottime — 21 283 calls in 3.627 s (1 209 ms/call under the profiler)**: `ImagingCore.resize` 0.972 s (24 calls = 8/layer-4-call), `numpy.ufunc.reduce` 0.626 s, `ImagingDecoder.decode` 0.538 s (PNG decode), `scipy.ndimage.uniform_filter1d` 0.488 s, `skimage.metrics.structural_similarity` 0.382 s, `numpy._methods._var` 0.195 s, `ImagingCore.convert` 0.078 s. **The resize is 27 % of layer 4 and SSIM's own machinery is a further ~35 %** — which is exactly why the "resize once" proposal does not pay (O-1, §10).

### 1.4 What is **NOT** a bottleneck (three hypotheses the brief named, measured and rejected)

| Hypothesis | Verdict | Evidence |
|---|---|---|
| **Fusion reload** | **INVALIDATED.** One load per process, then cached forever. | P7: **0** `json.loads` calls across 6 000 `layer9_fusion()` invocations. P6: 0.0135 ms/call. P8: the one-time load is 0.2985 ms. The `_model_lock` (`fusion.py:90`) guards only that one-time load; `layer9_fusion` itself takes **no** lock, so separate worker processes can never contend on it. **There is no fusion bottleneck and the lock is not a bottleneck.** |
| **Regex compilation per element/document** | **INVALIDATED.** Every pattern in the detection package is module-level `re.compile` (17 sites, all at import). Only **3** inline `re.*` call sites exist across `dom.py` + `signatures.py` (`dom.py:212`, `signatures.py:115`, `signatures.py:207`), and all three are served from CPython's 512-entry `re._cache` at **1.7 µs** (P10). | P9/P10/P11. The 54 ms module-import cost is paid once per worker process, in the parent, before fork — i.e. **~54 ms of the worker's total startup, per process, not per scan.** |
| **Missing DB index on the dispatcher's due-site query** | **NOT REPRODUCED as a gap** (Session A's measurement stands; my EXPLAIN sweep was on empty tables and is reported as untested — see §3). What I *did* establish independently is that the dominant per-query cost is **not the query**: P25 shows an 87–180 ms client round trip against a statement Postgres executes in **0.033–0.069 ms**. | P25. The real per-task DB cost is AUDIT-SA3-11's engine rebuild (P22/P23), which I reproduced at **95.06 ms vs 5.32 ms = 17.9×, 89.74 ms wasted per task**. |

---

## 2. `OPS-1` … `OPS-8`+

### OPS-1 — `update.ps1` does not merge `.env.example` into `.env`. At all. **[HIGH]**

**The brief's premise was wrong in a way that makes the finding stronger.** The brief says: "*Verify `.env.example` vs `.env` merge behavior (missing keys leading to broken upgrades).*" I expected to find a merge with a gap. **There is no merge code in `update.ps1`.** Proof:

- `update.ps1` contains **exactly five** references to `.env`, and **not one of them writes**:
  - `:6` and `:17` — comments (`:17`: "*Your data (Postgres volume, scan artifacts) and your `.env` are **never touched***").
  - `:31` `$EnvFile = Join-Path $RepoRoot ".env"`; `:64` `Fail ".env not found - run scripts\install.ps1 first."` — existence check only.
  - `:189-191` — `Get-Content $EnvFile` scanned for `WARDRESS_HTTP_PORT` so the health-wait loop knows where to poll.
  - `:218` — a console message.
- A repo-wide grep for `\.env` across `scripts/*.ps1` returns **49 matches in 4 files**; the only **write** of a `.env` anywhere in `scripts/` is `install.ps1:236` (`[System.IO.File]::WriteAllText($EnvFile, …)`), inside the `if ($FirstInstall)` branch. `install.ps1:247-254` — the "existing `.env`" branch — only checks for surviving `CHANGE_ME` markers and then writes nothing.
- `install.ps1:8-10` states the design in its own header: "*Generates .env from .env.example **on first run**… Idempotent: an existing .env is **NEVER touched**.*"

**There is no prompting, no merge, no atomicity question, and no key-removal question** — because there is no code path in which any of those can happen. The answer to "which keys are added / preserved / removed / what about a changed default" is: **none of them, ever, on any upgrade.**

**This is not theoretical. It has already happened on the user's live install.** Diffing the key sets of the real `.env` against `.env.example` (read-only):

| | count |
|---|---|
| `.env.example` keys (the documented set) | **24** |
| live `.env` keys | **11** |
| **In `.env.example` but MISSING from the live `.env`** | **14** — `PUBLIC_BASE_URL`, `ADMIN_RESET_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `RATE_LIMIT_PER_IP`, `RATE_LIMIT_PER_USER`, `RATE_LIMIT_WINDOW_SECONDS`, `TRUST_PROXY_HEADERS`, `ACCESS_TOKEN_TTL`, `REFRESH_TOKEN_TTL`, `MAX_SESSION_TTL`, `JWT_LEEWAY_SECONDS`, `MAX_REQUEST_BODY_BYTES`, `CORS_ALLOWED_ORIGINS`, `COOKIE_SECURE` |
| **In the live `.env` but NOT in `.env.example`** | **1** — `WARDDRESS_ENV`, which has **0 references anywhere in the repository** (grepped across `backend/app/**`, `backend/worker/**`, `docker-compose.yml`, `scripts/*.ps1`, `docs/**`, `*.md`, `*.ts`, `*.tsx`, `*.json`) |

The live `.env` cannot have been produced by the current `install.ps1` from the current `.env.example` (which copies every line verbatim). It has drifted 14 keys behind the documented set and carries one key nothing reads — and **no script will ever notice or reconcile it**, on this upgrade or any future one.

**Why this is High and not Medium.** The 14 missing keys split into three failure classes, and the first is a real trap:

1. **Documented-but-unset knobs silently do nothing.** `RATE_LIMIT_PER_IP` and `TRUST_PROXY_HEADERS` are both `${VAR:-default}` in `docker-compose.yml:54,57`, so compose substitutes the default and the operator's `.env` omission is invisible. For `RATE_LIMIT_PER_IP=300` that is harmless. For `TRUST_PROXY_HEADERS` it is not: the operator who reads `docs/configuration.mdx:71`, adds `TRUST_PROXY_HEADERS=true` to `.env`, and restarts gets a **silently still-false** rate limiter that trusts nothing — or, worse, one who instead sets it in the wrong place gets a different silent outcome. There is no "you have unset variables" message anywhere in the stack.
2. **Required-key breakage.** Every `${VAR:?…}` in compose (`POSTGRES_PASSWORD`, `DATABASE_URL`, `JWT_SECRET`, `CREDENTIALS_ENCRYPTION_KEY`) would make `docker compose up` **refuse to start** with a message naming a key the operator has never heard of and which is not in their `.env`. This is the *loud* class, which is the only reason this is not Critical: an operator who upgrades across a commit that introduces a new required key gets a compose error instead of a silent misconfiguration.
3. **Silent default drift.** A key that changes its default between releases leaves an upgraded install on the *old* value forever, with no record of which value is intended. Nothing in `.env.example` is versioned.

**`LOGIN_RATE_LIMIT_PER_IP` — Session A's `AUDIT-SA5-7`, independently verified and sharpened.** `app/config.py:86` `login_rate_limit_per_ip: int = 30`, consumed at `app/ratelimit.py:129`, exercised by `tests/conftest.py:33` and `tests/test_phase17_auth_audit.py:211,226`. It appears in **neither** `.env.example` **nor** `docker-compose.yml`. I verified the stronger consequence directly: `docker compose config | Select-String LOGIN_` returns **zero hits**, and the live `wardress-app-1` container's environment (names only) contains **26 variables, none of them `LOGIN_RATE_LIMIT_PER_IP`**. So the knob is not merely undocumented — **it is unsettable through `.env`**, because compose never forwards it. An operator who adds it to `.env` gets a completely silent no-op. It is the only such gap in the env-var surface: I cross-referenced all 24 `.env.example` keys against `backend/**/*.py`, `docker-compose.yml`, `scripts/*.ps1` and `docs/**` and **every one of the other 23 is referenced by code (py ≥ 2) or compose (≥ 1)**. `POSTGRES_DB` is the only key with **zero** doc hits (it appears in compose, `uninstall.ps1:154` and `install.ps1`, but in no `.mdx`/README table) — a documentation gap, not a functional one.

**Severity: High.** Justification: this is an operator-harming script defect by the brief's own definition, it has *already silently degraded the live install by 14 documented keys*, and it converts a future newly-required key into a boot failure. It is not Critical because the loud class fails closed and no data is at risk.

### OPS-2 — `validate.ps1` green-lights a configuration the measured deployment cannot survive **[HIGH]**

**What it actually checks** (`validate.ps1:185-217`, step 8 of 8):

```powershell
$dockerInfo = docker info --format json | ConvertFrom-Json
$cpus = $dockerInfo.NCPU
$memGB = [math]::Round($dockerInfo.MemTotal / 1GB, 1)
if ($memGB -lt 4) { Add-ValidationWarning "Less than 4GB RAM allocated to Docker - builds may be slow" }
if ($cpus  -lt 2) { Add-ValidationWarning "Less than 2 CPUs allocated to Docker - builds may be slow" }
```

Replayed against the live engine, line for line:

| quantity | value | note |
|---|---|---|
| `docker info` `MemTotal` | **7 976 714 240 B** | |
| `$memGB` = `Round(7976714240 / 1073741824, 1)` | **7.4** | PowerShell's `1GB` is 1 073 741 824, not 10⁹ |
| `$memGB -lt 4` | **`False`** → **silent pass, no warning** | |
| `NCPU` / `$cpus -lt 2` | 12 / `False` | |

**What it does NOT check** (grep for `Disk|Get-PSDrive|port|Listen|NetTCP|8321|Get-NetTCP` in `validate.ps1` → **zero hits**):
- **Disk space.** `install.ps1` then pulls and builds four multi-GB Docker images and writes an unbounded artifacts volume onto the same drive (AUDIT-SA3-2 projects ~9.6 GB/day of artifacts at 500 sites/60 min). `diagnostics.ps1:372` *does* warn at < 10 GB free — **the diagnostics script checks a resource the pre-install validator does not.**
- **Port availability.** `WARDRESS_HTTP_PORT` defaults to 8321 and compose publishes `"${WARDRESS_HTTP_PORT:-8321}:8000"`. Nothing checks it is free, so a pre-existing listener produces a `docker compose up` bind failure *after* a multi-minute build.
- **The host-vs-VM memory relationship.** This is the substantive gap. The measured facts on this machine:

| | value |
|---|---|
| Docker VM ceiling (`docker info` `MemTotal`) | **7.43 GiB** |
| Host total physical RAM | **15.34 GiB** |
| Host RAM free at probe time | **4.46 GiB** |
| 12 fully warm prefork children (Session A, measured) | **5.90 GiB = 79 % of the ceiling** |
| A single warm child's non-reclaimable floor (Session A) | **624.5 MB** (GC returns 0.2 MB) |

`validate.ps1` reads only the **7.43 GiB** figure. It never compares it to the host's 15.34 GiB, so it cannot tell the operator that **Docker Desktop has been silently capped at 48 % of their machine's RAM** — which is the single most important resource fact for this deployment, and the one an operator cannot see without knowing to look. And it compares 7.43 GiB against a threshold of 4 GiB, so it emits **nothing at all** on a machine where 12 warm children alone want 5.90 GiB and the remaining 1.53 GiB has to hold Postgres, Redis, the API, beat, the browser processes and Docker's own overhead.

**The threshold is also on the wrong quantity and the wrong axis.** The warning text is "*builds may be slow*" — it is framed as a **build-time** concern, when the real risk is a **steady-state** one: a warm pool that cannot fit is an OOM spiral, and per Session A `restart: unless-stopped` never restarts an OOM-looping-but-alive worker, and the worker has no healthcheck. So the one check that exists is (a) below the real requirement, (b) about the wrong phase, and (c) silent on this exact host.

**Severity: High.** Justification per the brief's own rule: "*an operator-harming script defect (e.g. a `validate.ps1` that green-lights a configuration the measured deployment cannot survive) is High*." It is not Critical — the stack *is* running here, and 79 % is tight, not fatal.

### OPS-3 — `install.ps1` preflight: what it does, and the four checks it is missing **[MEDIUM]**

Read-only analysis of all 17 steps (no run, per Rule 15). What it *does* check, in order: docker CLI present (`:90`), engine responsive within 30 s (`:95-98`), engine actually running (`:100-103`), `docker compose` plugin present **and** responsive (`:105-113`), pnpm present → `npm install -g pnpm` fallback (`:135-145`), `node_modules` present or `pnpm install --frozen-lockfile` (`:154-168`), `pnpm run type-check` clean (`:174-178`), `.env.example` present (`:184-186`), and later a 120 s `/api/health/live` wait (`:325-348`) plus `app.seed_admin` exit code (`:354-357`).

**What it does NOT check — four gaps, in rough order of harm:**

1. **Node.js is never checked.** `validate.ps1:94-104` checks it (and requires ≥ 18); **`install.ps1` does not.** `install.ps1:135-145` only looks for `pnpm`, and if pnpm is missing falls back to `npm install -g pnpm` — which on a machine with Node 14, 16 or 20 produces a pnpm whose own engine constraint is violated, and the failure surfaces as an opaque `pnpm install` error **after** the Docker engine probes have already burned 60 s. There is no `node --version` call anywhere in `install.ps1` (grep: zero hits).
2. **Port availability.** As OPS-2. `install.ps1` never checks that `WARDRESS_HTTP_PORT` is free. The build is serial and takes minutes; a port clash is discovered at `Invoke-Compose @("up","-d",...)` (`:309`), i.e. *after* everything has been built.
3. **Existing-install / partial-prior-run detection.** `$FirstInstall = -not (Test-Path $EnvFile)` (`:188`) is the *only* state check. There is no detection of a half-finished prior run: a `.env` with no containers, containers with no `.env`, a `db-data` volume from an older schema (which is precisely the AUDIT-SA3-8 un-migrated-schema scenario), or a `.env` whose `POSTGRES_PASSWORD` no longer matches the volume's initialised role password. In the last case, `alembic upgrade head` (`:306`) fails with an opaque `password authentication failed for user "wardress"` and the script's own hint (`:356`) points at `ADMIN_EMAIL`/`ADMIN_PASSWORD`, which have nothing to do with it.
4. **Disk space**, as OPS-2.

**Idempotency — verified good, one documented exception.** Re-running is safe: `.env` is never touched (`:248`), `alembic upgrade head` is a no-op at head, `seed_admin` is explicitly idempotent (`:353`), and `Invoke-Compose @("up","-d",...)` is convergent. The one exception is the **Desktop shortcut** (`:361-376`): it is created inside a `try/catch` that swallows every failure (`:373-376`), and it uses `WScript.Shell.CreateShortcut` on a fixed path `Wardress.lnk`. On re-run it **overwrites unconditionally** rather than checking for an existing one — which is correct for a *reinstall* (the URL may have changed) and mildly destructive for a *user-modified* shortcut. It also does not verify `$dashboardUrl` still resolves, and the `$IconFile` check (`:369`) silently omits the icon if `assets\brand\wardress.ico` is absent. **Low**, and correctly non-fatal by design (the comment says so).

### OPS-4 — `diagnostics.ps1` secret scrubbing: the `wk_` claim is **FALSE**, and 9 of 16 hostile shapes escape **[HIGH]**

The brief asks: "*Verify secret scrubbing rules (ensure `wk_` API keys and tokens in service logs are scrubbed).*"

**Method (Rule 15 compliant).** `diagnostics.ps1` is read-only with respect to the deployment — I read all 395 lines and confirmed the only writes are `$OutputPath` (defaulted to `Documents`, `:24-28`) and `pnpm run type-check`'s own cache. I therefore tested the scrubbing **in isolation** rather than running the whole bundle: `Get-SecretScrubbers` (`:30-66`) and `Protect-Line` (`:68-73`) were copied **verbatim** into `C:\Users\Ns8pc\AppData\Local\Temp\opencode\w1c\scripts\scrub_probe.ps1`, with **one** change — `$RepoRoot` repointed at a synthetic fixture directory holding a **100 % fake** `.env`. **The real `.env` was never read; no live credential entered the harness, the transcript, or this report.** 16 hostile-*shaped* probes, all synthetic.

**The rules it builds (10, from the fake fixture):** 6 exact-value rules (`.env`'s `POSTGRES_PASSWORD`, `DATABASE_URL`, `JWT_SECRET`, `CREDENTIALS_ENCRYPTION_KEY`, `ADMIN_PASSWORD`, `TELEGRAM_BOT_TOKEN`, each `[regex]::Escape`d, each gated on `Length >= 8` and not `*CHANGE_ME*`) + 4 generic shapes: `sk-[A-Za-z0-9_-]{8,}`, `xox[baprs]-[A-Za-z0-9-]{8,}`, `gh[pousr]_[A-Za-z0-9]{20,}`, `AKIA[0-9A-Z]{16}`.

**Result: `scrubbed=7 escaped=9 (of 16)`.**

| probe (shape only) | outcome |
|---|---|
| **`wk_` API key, `Authorization: Bearer wk_…` (43 urlsafe)** | **ESCAPED verbatim** |
| **`wk_` key in a query string `?api_key=wk_…`** | **ESCAPED verbatim** |
| **`wk_` key inside a JSON error body** | **ESCAPED verbatim** |
| **JWT access token** (`eyJ….….…`, 3 base64url segments) | **ESCAPED verbatim** |
| **Fernet key** (`gAAAAA…`, 44 chars) | **ESCAPED verbatim** |
| **Telegram bot token shape** (`<digits>:AA…`, a *different* token from the configured one) | **ESCAPED verbatim** |
| **Apprise URL with embedded credential** (`scheme://user:hunter2@host/token…`) | **ESCAPED verbatim** |
| **`postgresql://user:pass@host/db` in a log line** | **ESCAPED verbatim** |
| **bare base64 blob (32 B)** | **ESCAPED verbatim** |
| `sk-proj-…` | SCRUBBED |
| `AKIA…` | SCRUBBED |
| `xoxb-…` | SCRUBBED |
| `ghp_…` | SCRUBBED |
| a line dumping 3 `.env` secrets | SCRUBBED |
| the *configured* `TELEGRAM_BOT_TOKEN` | SCRUBBED |
| the configured `DATABASE_URL` | **PARTIALLY** scrubbed → `postgresql+asyncpg://wardress:<redacted>@db:5432/wardress` |

**The named `wk_` claim is false, and it is false in the most specific way possible.** `app/apikeys.py:13-21` is unambiguous:

```python
API_KEY_PREFIX = "wk_"
DISPLAY_PREFIX_CHARS = 8
raw = API_KEY_PREFIX + secrets.token_urlsafe(32)   # -> wk_ + 43 chars of [A-Za-z0-9_-]
```

`diagnostics.ps1`'s generic list contains `sk-`, `xox[baprs]-`, `gh[pousr]_` and `AKIA` — and **`wk_` is not one of them.** The product's own primary API-key format, in its own support bundle, is unredacted. For calibration, the scrubber *does* cover `sk-` and `ghp_` — **third-party** tokens the product never issues — while missing the one format it issues itself.

**Two aggravating factors:**

1. **Exposure path.** A full `wk_` key is returned exactly once, by the key-creation response, and is stored only as a SHA-256 hash with an 8-char display prefix. So the *steady-state* log exposure is low. But the bundle also captures, unredacted, `docker compose logs --tail=50` for five services (`:207-222`) and the **verbatim `docker info`** (`:141`). Any future code path that logs a request header, an agent transcript, an LLM prompt, or a Telegram message containing a pasted key lands in a file whose own footer (`:395`) tells the user "*Secret-bearing values are redacted; share this file when requesting support.*" **That sentence is false**, and it is false in the direction that matters: it invites the user to attach the bundle to a public issue.
2. **The partial `DATABASE_URL` redaction is an ordering bug, not just incompleteness.** The rules are applied in list order, and `POSTGRES_PASSWORD` (index 0) is applied *before* `DATABASE_URL` (index 1). So the password rule rewrites the URL first, `DATABASE_URL`'s own exact-value rule no longer matches, and the **host, port, database name and username survive**. A support bundle is meant to be shareable; leaking `wardress@db:5432/wardress` alongside a bundle is a small but real information disclosure, and it demonstrates that the rule set was never tested against a *composition* of its own inputs.

**Directly analogous precedent, escalated by Session A:** `AUDIT-4E-8` (High) — heuristic redaction lets a 9-character custom-endpoint key survive into the dict persisted as layer-8 `ScanFinding.evidence` and into an HTTP 503 body, reaching a Viewer. That is the same root cause in a different surface: **redaction is a per-shape allowlist with no default-deny.** The two findings compound: a key that survives into `ScanFinding.evidence` in the database is exactly the kind of string that would then be echoed into a log line and into the support bundle.

**Severity: High.** Justification: a false "clean" in a *share-this-file* artefact, on the product's own primary credential format, is operator/security harm rather than cosmetic drift. Not Critical: the realistic exposure requires a key to reach a log line, and no such path exists in the code I read.

### OPS-5 — Backup & Restore: the backup's own completeness model has a hole, and the restore can silently half-fail **[HIGH]**

Per §2 of my brief: **static analysis only. `uninstall.ps1` was not run.** Confidence: **medium-high** on the static conclusions; the end-to-end replay is **UNVERIFIED**.

**What the backup produces** (`uninstall.ps1:113-338`), in order: `.env` (`:141-142`), `database.sql` via `pg_dump --clean --if-exists` produced **inside** the container and copied out with `docker compose cp` (`:181-188`, byte-exact by design — the comment at `:176-180` correctly explains that redirecting through the Windows PowerShell 5.1 text layer would re-encode to UTF-16LE+BOM and corrupt every non-ASCII character, which is a genuinely good piece of engineering), `scan-artifacts.tar.gz` (`:251-284`), and `RESTORE.txt` (`:288-330`).

**Bidirectional coverage cross-check** — every artifact produced vs every artifact consumed:

| artifact produced | referenced by `RESTORE.txt`? | artifact `RESTORE.txt` needs | produced by the backup? |
|---|---|---|---|
| `.env` | ✅ step 1 (`:313-316`) | `.env` | ✅ |
| `database.sql` | ✅ step 3 (`:319-322`) | `database.sql` | ✅ |
| `scan-artifacts.tar.gz` | ✅ step 4 (`:323-326`) | `scan-artifacts.tar.gz` | ⚠️ **conditionally — see defect B** |
| — | — | a running `db` container | ✅ step 2 runs `install.ps1` first |
| — | — | a migrated schema **matching the new image** | ❌ **NO — see defect A** |
| — | — | `helperImage` (the `db` image ref) | ✅ present after step 2 |
| — | — | **Redis volume contents** | ❌ not produced, not needed (see below) |
| — | — | **Ollama models volume** | ❌ not produced (re-pullable) |

**Defect A — the restore silently downgrades the schema below the running binary [HIGH].** `RESTORE.txt`'s ordering is: step 2 = `install.ps1` (which runs `alembic upgrade head`, `:305-306`) → step 3 = `psql -f database.sql` (which replays the dump's `DROP`/`CREATE`, reverting the schema to whatever the backup was taken at) → step 5 = `docker compose up -d`. **There is no `alembic upgrade head` after the load.** If the backup is older than the checkout being restored into — the *normal* case, and the *only* case where restoring is interesting — the operator ends up running a **new** app image against the **old** schema, with no migration error, no startup failure, and 500s/empty lists on any query touching a newer column. This is AUDIT-SA3-8's silent schema/code mismatch, reachable through the officially documented recovery path. `RESTORE.txt` is generated from what the run captured (`:286-287` "*Generated from what THIS run actually captured — never a hardcoded manifest*") — which is good discipline for the **contents** section and precisely why the **absence of a migration step** is conspicuous: the generator knows exactly what it captured and still omits the step that makes it loadable.

**Defect B — a missing artifacts volume is reported as a *complete* backup [MEDIUM].** `uninstall.ps1:252` hardcodes `$artVol = "${Project}_scan-artifacts"` with `$Project = "wardress"` (`:52`, commented "*docker-compose.yml `name:`*"). Docker Compose, however, reads **`COMPOSE_PROJECT_NAME` from the same `.env` file** and overrides the `name:` key. If an operator has ever set that variable — a completely normal thing to do when running two stacks on one machine — then:

- `docker compose down -v` correctly removes `mywardress_scan-artifacts` (it resolves the project name itself);
- but `:254 Invoke-Quiet { docker volume inspect wardress_scan-artifacts }` looks for the **wrong name**, fails, and falls into `:282-284`:
  ```powershell
  Write-Host "    No scan-artifacts volume found - skipping" -ForegroundColor Yellow
  ```
  — which prints a yellow line and **does not add anything to `$missing`**;
- so the completeness check at `:332-337` reports **`Backup completed successfully`**, `exit 0`, and then `:356` `docker compose … down -v` **destroys the volume**;
- the same hardcoding affects the fallback volume sweep at `:370-375`.

The result: **every stored screenshot and captured page for the whole fleet is destroyed, and the tool reported a clean backup.** The same structural hole exists for `.env` at `:141-147`: a missing `.env` prints a warning and is **not** recorded in `$missing`, on the stated rationale (`:116-118`) that "*Components that do not exist at all (no `.env` yet…) are gaps, not failed captures*". That rationale is sound for a never-installed stack, but it is wrong for an operator who moved or deleted `.env` — because the DB dump then contains **Fernet-encrypted SMTP credentials, Telegram tokens, Apprise URLs and AI provider keys** (`CREDENTIALS_ENCRYPTION_KEY` lives only in `.env`), and every one of them becomes **permanently undecryptable** the moment `wardress_db-data` is removed. The script has a `-AllowIncompleteBackup` switch (`:30-34`) and an `exit 2` code (`:451`) precisely for this class of loss — and neither fires.

**Defect C — the restore reports success on a partial load [MEDIUM].** `RESTORE.txt` step 3 (`:321`) is:

```
docker compose exec -T db psql -U <user> -d <db> -f /tmp/restore.sql
```

`psql`'s default is `ON_ERROR_STOP` **off**, which means it **continues past errors and still exits 0**. `docker compose exec` propagates the exit code. So a restore that failed halfway — a missing table, a permissions error, a disk-full on the WAL — prints a wall of `ERROR:` lines and **the operator's script reports success**. Compare the backup half, which is *careful*: it sanity-checks that the dump begins with `--` (`:207-233`) precisely because "*a zero-byte or binary-garbage file is a failed capture even when every command exited 0*". **The same discipline was applied to the write side and omitted from the read side.** One token (`-v ON_ERROR_STOP=1`) closes it.

**Defect D — `RESTORE.txt` is written with `-Encoding UTF8` (`:330`), which is UTF-8-**with BOM** under Windows PowerShell 5.1 and UTF-8-**without BOM** under PowerShell 7+ (the scripts otherwise target both — see `New-RandomSecret`'s explicit 5.1 compatibility note at `:57-59`).** A restore note with a BOM renders as `â€¦Wardress backupâ€¦` in some editors, and a copy-paste of its first line fails. **Low.**

**Defect E — a dead guard.** `:323 if ($hasTar -and $helperImage)`. `$helperImage` is assigned at `:253` **only inside** `if (Invoke-Quiet { docker volume inspect $artVol })`, and `:134` clears the three managed filenames from a reused `-BackupPath` first — so `$hasTar` true implies the volume existed implies `$helperImage` non-null. The `&& $helperImage` half can therefore never be false when it matters. Harmless, but it is the kind of condition that *looks* like it defends against something. **Low / cosmetic.**

**What the backup correctly does NOT need to cover** (so the reader can calibrate the real exposure): the `redis-data` volume holds the Celery result backend (24 h TTL, ~500 KB/day, `AUDIT-SA3-12`) and the broker queue — all reconstructible, and the DB stale sweep recovers a lost message (Session A). `ollama-data` holds re-pullable model weights. Neither is a data-loss surface. **The genuine gap against AUDIT-SA3-2 is that the backup is a full logical dump of a database and volume whose growth is unbounded** — which is a capacity finding, not a backup-correctness finding, and I record it as such.

**What a live run would still be needed to confirm:** (a) that `pg_dump`'s output actually survives `docker compose cp` byte-exact on this host, (b) that the `docker run -v $dstMount` at `:266` handles a repo path containing spaces (`$dstMount = $backupDir + ":/backup"` is passed **unquoted** to a native command — PowerShell does add quotes for space-containing native args, so this is *probably* fine, but "probably" is not a measurement, and the workspace path here happens to contain no spaces while a user's `C:\Users\John Doe\…` would), and (c) that `RESTORE.txt`'s `copy "<repo>\.env"` line works when the backup folder name contains spaces. I did not run any of it.

### OPS-6 — `lib.ps1`: a Windows argument-quoting bug that is currently unreachable, and an error-handling gap **[MEDIUM / LOW]**

**`Quote-Arg` (`lib.ps1:89-92`) mishandles a trailing backslash.**

```powershell
function Quote-Arg([string]$Value) {
    if ($Value -match '[\s"]') { return '"' + ($Value -replace '"', '\"') + '"' }
    return $Value
}
```

`Invoke-NativeWithDeadline` builds a raw `.Arguments` **string** (`:104-109`) and hands it to `ProcessStartInfo`, so the quoting is this function's responsibility alone. It wraps any value containing whitespace or a `"` in double quotes, but **does not double a trailing backslash**. Under `CommandLineToArgvW` rules, `"C:\some path\"` has its closing quote **escaped** by the backslash, so the argument swallows the rest of the command line. This is a real, well-known Windows bug class and the fix is one line (`$Value -replace '(\\+)$', '$1$1'` before the closing quote).

**It is currently unreachable, and I am reporting it as latent rather than as a live defect.** I traced every call site: `Invoke-NativeWithDeadline` is invoked exactly **six** times in the whole script set, always with a fixed argument vector — `docker @("info")` (`install.ps1:95,105`; `update.ps1:51`; `uninstall.ps1:73`; `validate.ps1:54,64,189`) and `docker @("compose","version")` (`install.ps1:105`; `validate.ps1:64`). **No user-controlled path ever reaches `Quote-Arg`.** Paths that *do* vary (the repo root, the build-log directory, the backup directory) are handled by `Join-Path` + `Push-Location` + `Set-Location`, or by `Start-Process -ArgumentList` (`lib.ps1:358`), which applies its own quoting. So: **Medium as a latent trap for the next caller, zero current operator impact.** Recording it so the remediation prompt does not discover it as a mystery later.

**Error handling across the script set is genuinely good, with two named exceptions.** Every entry point sets `$ErrorActionPreference = "Stop"` and `Set-StrictMode -Version Latest`. `Fail()` (`:12-16`) prints a readable red message and `exit 1`. `Invoke-Compose` (`:150-156`) checks `$LASTEXITCODE` and calls `Fail` with the failing command echoed. `Build-Service` (`:326-403`) caches `$process.Handle` (`:363`) — with the correct comment "*otherwise, ExitCode returns $null after process termination*" — keeps build logs in a dedicated directory (never the repo root), prints them on failure, and `Fail`s. `Invoke-WithRetry` (`:186-220`) correctly distinguishes retryable network errors from `error TS\d+`/`ELIFECYCLE` compilation errors and refuses to retry the latter. That is more careful shell engineering than most projects have.

**The two exceptions:**

1. **`diagnostics.ps1:15` sets `$ErrorActionPreference = "Continue"` and never sets an explicit exit code.** So the support-bundle script **exits 0 even when Docker is dead, the worker is down, and the dashboard is unreachable** — a bundle that is entirely `UNREACHABLE` lines still reports success. Anyone gating on its exit code is gated on nothing. **Medium** (it is the *diagnostic*, so a false success there misroutes triage).
2. **`uninstall.ps1:363-366` swallows a non-zero `docker compose down` exit** and continues to a best-effort sweep — which is *correct* for a teardown (idempotent, and the sweep at `:370-375` catches the stragglers) and is honestly labelled "*Continuing to a best-effort sweep*". **Not a defect.** Recording it so the coordinator can see it was considered.

### OPS-7 — Idempotency of every script, and `generate_structure.py` **[LOW]**

**Idempotency, verified by reading, not by running:**

| script | re-run behaviour | verdict |
|---|---|---|
| `install.ps1` | `.env` untouched (`:248`); `alembic upgrade head` no-op at head; `seed_admin` explicitly idempotent (`:353`); `compose up -d` convergent; shortcut overwritten unconditionally (`:369-370`) | **idempotent**, with the documented shortcut exception |
| `update.ps1` | `git pull --ff-only` (no-op when up to date); `docker compose build --pull` (cache-warm no-op); `alembic upgrade head` no-op; `--force-recreate beat` is **deliberately not idempotent but deliberately required** — `:167-169` explains it: `up -d` does not recreate a running container whose own config is unchanged, and beat shares the worker image, so without the force it "would silently keep the old code". **That is a genuinely good catch and the comment is accurate.** | **idempotent and correct** |
| `uninstall.ps1` | `:132-137` explicitly removes the three managed filenames from a reused `-BackupPath` so the folder always describes *this* attempt — thoughtful. `compose down -v` is convergent. | **idempotent** |
| `validate.ps1` | Pure read + `pnpm install --frozen-lockfile` (a no-op when `node_modules` exists, `:155`) + `pnpm run type-check` | **idempotent** |
| `diagnostics.ps1` | Writes a **timestamped** file (`:19,27`), so re-running does not overwrite a previous bundle. | **idempotent** |

**`generate_structure.py` is an orphan.** 9 137 B, 250 lines, `main()` at `:197` walking `Path(__file__).resolve().parent.parent` and writing a report to a path derived at `:248`. Grepped across `scripts/*.ps1`, `README.md`, `docs/**` (including the Mintlify skill), `frontend/package.json` and `backend/pyproject.toml`: **zero references.** It is not invoked by any script, documented anywhere, or wired into any workflow. It is a one-shot developer utility that has become unreferenced surface area. **Low** — zero behavioural impact, and it is plausible the user values it as a personal tool. Flagged as a decision for the user, not a defect.

**Two robustness notes in it worth recording:** it opens files **twice** in `get_line_count` (`:74` binary to sniff for a NUL, then `:78` text) and bails with `"Large (Skipped)"` at `:71` before opening anything huge — that is the right shape. And `is_temp_entry` (`:39`) is called from `build_tree` (`:90`) but there is no `visited` set passed at the only call site I could see, so symlink loops on Windows are unlikely but junction loops are not obviously excluded. Not investigated further; out of budget.

### OPS-8 — Cross-script consistency: three drifted copies of the same knowledge **[MEDIUM]**

The script set has **no single source of truth** for three facts that all five scripts need, and they have already drifted:

1. **The dashboard port.** `install.ps1:267-269` reads it from `.env` with a `8321` fallback. `update.ps1:188-192` reads it with a `Get-Content | Select-String` loop and a `8321` default. `diagnostics.ps1:299` reads it a **third** way, with no fallback at all (`if ($envMap.ContainsKey(...)) { … } else { "8321" }` — fine, but a third implementation). `uninstall.ps1` and `validate.ps1` don't need it. **Three implementations, one behaviour, no shared helper** — and `lib.ps1` already hosts a dozen shared helpers, so the omission is an oversight, not a design choice.
2. **The database user/name.** `uninstall.ps1:150-156` parses `POSTGRES_USER`/`POSTGRES_DB` out of `.env` with a hardcoded `wardress`/`wardress` fallback (correctly, "*defaults match docker-compose.yml*"), and the values are then **interpolated into `RESTORE.txt`'s operator-facing commands** at `:321` and `:325`. If the fallback ever applies, the restore note tells the operator to run `psql -U wardress -d wardress` against a database called something else. The template is the right place for this; the *derivation* is the fragile part.
3. **The health endpoint.** `install.ps1:335`, `update.ps1:203` and `diagnostics.ps1:300` all hit **`/api/health/live`**. That is the *correct* choice (see DOC-7/§3), and it is notable that all three got it right while `health.py:66-67`'s own docstring still describes a different contract. So the scripts are ahead of the code's documentation here.

**Severity: Medium.** No current misbehaviour; this is the drift *class* the brief asked me to expand into, and it is the mechanism by which OPS-5's defects will multiply if the scripts keep growing.

---

## 3. Docker topology

### 3.1 The dependency graph **as found** (from `docker-compose.yml`, 168 lines, 7 services)

```
            ┌──────────────────────── depends_on ────────────────────────┐
  db  ◄─────┤ healthy (pg_isready, 5s/5s/×10)                            │
  redis ◄───┤ healthy (redis-cli ping, 5s/5s/×10)                        │
            └───────────────────────────────────────────────────────────┘
  app       ──► db(healthy) + redis(healthy)          [HEALTHCHECK ✔ /live]
  worker    ──► db(healthy) + redis(healthy)          [no healthcheck]
  beat      ──► redis(healthy)                        [no healthcheck]  ◄── MISSING db
  telegram-bot ─► db(healthy) + redis(healthy)        [no healthcheck]  (profile)
  ollama    ──► (nothing)                             [no healthcheck]  (profile)
```

**Every missing or wrong edge I could find — 4 defects:**

| # | defect | evidence | consequence |
|---|---|---|---|
| D1 | **`beat` has no `depends_on: db`** | `docker-compose.yml:129-131` — `depends_on` contains **only** `redis` | **CONFIRMED** (Session A `AUDIT-SA3-7`). Four of the five beat tasks require the DB (`_dispatch_due_scans`, `_resweep_undelivered`, `_cleanup_orphan_artifacts`, `expire_agent_actions`, `sync_model_catalog`); only the publish needs Redis. On a cold `docker compose up`, beat's first tick can fire before Postgres accepts connections — and per AUDIT-4B-6 a failing tick **writes no heartbeat** and its recovery is the *next* tick, up to 64.18 s later, while the health page shows "Beat stalled". |
| D2 | **`worker` has no healthcheck** | `docker-compose.yml:89-116`; the only three healthchecks in the file are at `:17` (db), `:28` (redis), `:82` (app) | **CONFIRMED.** The one failure mode Session A's `AUDIT-4B-7` describes — an OOM-looping-but-alive worker — is **invisible to Docker, to `docker compose ps`, and to `restart: unless-stopped`** (which only restarts a container that *exits*). |
| D3 | **`beat` has no healthcheck** | `docker-compose.yml:118-131` | **CONFIRMED.** Same class. |
| D4 | **`telegram-bot` and `ollama` have no healthcheck**; `ollama` has no `depends_on` at all | `docker-compose.yml:136-162` | `telegram-bot` at least declares `db`+`redis`; `ollama` declares nothing, which is correct (it has no dependency) but it also has no healthcheck, so `docker compose --profile ollama up -d` reports "started" for a container that may be failing to pull a model. **Low.** |

**What is correct** (verified, not assumed): `beat` **does** receive `DATABASE_URL` (`docker-compose.yml:125`) and therefore does import `worker.db` — so D1 is a *declared-dependency* gap, not a "beat doesn't need the DB" case. All three of `app`/`worker`/`beat` correctly get the required-secret set, and `telegram-bot` gets `TELEGRAM_BOT_TOKEN` (`:144`) which the others correctly do not. `app`'s artifacts mount is `read-only: true` (`:76`) with the comment "*the app serves screenshots; only the worker writes*" — correct least privilege, and `worker`'s is read-write (`:111`).

### 3.2 Healthcheck correctness — the `AUDIT-SA4-9` question, answered

**The compose `app` healthcheck is CORRECT and is not affected by `AUDIT-SA4-9`.** `docker-compose.yml:83`:

```yaml
test: ["CMD", "curl", "-sf", "http://localhost:8000/api/health/live"]
```

It targets **`/api/health/live`**, not `/api/health`. `health.py:58-61` is:

```python
@router.get("/live")
async def liveness() -> dict[str, str]:
    """Unauthenticated process liveness — no dependencies touched."""
    return {"status": "ok"}
```

No DB, no Redis, no `except`. I verified `curl` is present and working in the image (`docker exec wardress-app-1 sh -c 'command -v curl'` → `/usr/bin/curl`, curl 8.14.1), and the container reports **healthy**. The config is also sane: `interval: 10s`, `timeout: 5s`, `retries: 5`, `start_period: 15s` → 65 s to first "unhealthy", comfortably inside `install.ps1`'s 120 s wait.

**So where `AUDIT-SA4-9` *does* bite is in the code's own documentation, and that is mine to report.** `health.py:64-70`:

```python
@router.get("")
async def readiness(db: DB) -> dict[str, str]:
    """Unauthenticated readiness (process + DB). Backward-compatible with
    the Phase 0 compose healthcheck, which curls /api/health."""
    if await _db_ok(db):
        return {"status": "ok", "service": "wardress-api"}
    return {"status": "degraded", "service": "wardress-api", "detail": "database unreachable"}
```

**The docstring's claim is false**: the compose healthcheck curls `/api/health/**live**` (`docker-compose.yml:83`). I confirmed this independently of Session A. Consequences:

- `/api/health` therefore has **no operational consumer anywhere** — not compose, not `install.ps1:335`, not `update.ps1:203`, not `diagnostics.ps1:300` (all three use `/live`). It is an **orphaned public route** that returns `200` in the degraded branch (Session A's finding: a status-code probe would read it as healthy) **and** discloses `"database unreachable"` to an **unauthenticated** caller.
- Measured live just now: `GET /api/health` → **200, 40 bytes**; `GET /api/health/live` → **200, 15 bytes**. So the route is reachable, unauthenticated, and returns distinguishable content — a free, unmetered oracle for "is the database up", which is exactly the reconnaissance an attacker wants before choosing between a DB-credential attack and something else.
- I am **not** re-litigating Session A's `AUDIT-4C-5`; I am adding the independently-measured confirmation and the new observation that the route is **fully orphaned from operations**, which strengthens the case for either deleting it or fixing its contract.

### 3.3 Worker memory limits, cgroups, recycling **[CONFIRMED — not re-litigated]**

I did **not** repeat Session A's memory measurement (out of contention budget, and the numbers are load-bearing and uncontested). What I independently verified:

- `docker-compose.yml:89-116` — the worker service has **no** `deploy.resources.limits`, **no** `mem_limit`, and **no** `healthcheck`.
- The only three healthchecks in the file are db/redis/app, so there is nothing to inherit.
- `Get-ComposeRemoteImages` (`lib.ps1:256-282`) explicitly filters to services with `image:` and **no** `build:`, so the worker's limits could not be coming from a shared anchor — there isn't one.
- Session A's three load-bearing numbers stand and I use them as inputs to OPS-2: **624.5 MB** non-reclaimable per warm child (GC returns 0.2 MB), **12 warm children = 5.90 GiB = 79 %** of the **7.43 GiB** ceiling I re-measured via `docker info`, and **`--max-tasks-per-child` provably does not help** because the memory is never returned.

**Configured worker concurrency: there is none.** `Dockerfile.worker:36` runs `celery -A worker.celery_app worker --loglevel=info` with **no `-c`**, so concurrency defaults to the container's CPU count — `os.cpu_count()=12` in-container (Session A's live `celery inspect stats` agrees: `max-concurrency: 12`). **The 79 % projection is therefore real and is the *default* behaviour**, not a misconfiguration someone chose. It is also why `validate.ps1`'s 4 GB threshold is so far off: the number it should be reasoning about is `12 × 390 MB marginal`, and nothing in the repository connects those two facts.

### 3.4 The beat schedule file **[CONFIRMED, undocumented]**

`docker inspect wardress-beat-1 --format '{{json .Mounts}}'` → `[]` (Session A). `/app/celerybeat-schedule.db`, 12 288 B, `PersistentScheduler`. It lives in the container's writable layer with no volume, so it is lost on container recreate. **I confirm Session A's judgement that this is benign by construction** — all five periodic tasks are idempotent (Session A's clean-ledger item, and I re-verified the idempotency of all five scripts in OPS-7) — and that it is **undocumented**. `docs/*.mdx`, `README.md` and the Mintlify `SKILL.md` contain no mention of it. Adding one sentence to `docs/installation.mdx` closes this at zero risk. **Low.**

### 3.5 Migrations run only from the PowerShell scripts **[CONFIRMED — Session A `AUDIT-SA3-8`]**

`alembic upgrade head` appears in exactly two production call sites: `scripts/install.ps1:306` and `scripts/update.ps1:160`. Neither Dockerfile runs it, and `app/main.py`'s lifespan runs `bootstrap_migration()` (the legacy AI-settings migration) and `bootstrap_catalog()` — **not** Alembic. So `docker compose up -d --build` on a new commit starts the app against an un-migrated schema, and the failure is **silent** (empty lists / 500s on any query touching a new column, no migration error anywhere). And per **OPS-5 defect A**, the officially documented *restore* path also ends with an un-migrated schema. **Medium**, unchanged.

---

## 4. Soft-block baseline poisoning (`NB-CAP-2`) — **PROVEN end to end**

**The question:** can a non-error (200-OK) block/paywall/verify-human page be mistakenly stored as a healthy baseline, and if so what happens?

**The answer: yes, and the consequence is a permanent false-alert generator.** Driven through the **real Celery task bodies** (`capture_baseline`, `run_scan`) against a **dedicated scratch database** (`wardress_w1c_test` on `wardress-test-pg`, created and **dropped** by me; `wardress-db-1` never contacted), with **only** `fetch_page` and `probe_site` stubbed. Artifacts, hashing, all 9 detection layers, fusion, the verdict gate, alert creation, `_schedule_next` and the scan row write were **all real**. Artifact root redirected in-process via `worker.artifacts.artifacts_root` (the single chokepoint every reader/writer goes through) so nothing was written outside scratch — verified afterwards that `C:\data` (the Windows resolution of the default `/data/artifacts`) does not exist.

### 4.1 The three-piece mechanism, each verified independently

| piece | file:line | verified how |
|---|---|---|
| The baseline guard is `http_status >= 400` and nothing else | `worker/scan_tasks.py:109-119` | source read + **positive control below** |
| The challenge detector recognises **Cloudflare markers only** | `worker/fetcher.py:187-201` | source read of the whole function: `if has_challenge_marker or is_challenge_title(title): return True` / `if http_status == 403 and headers: return "cf-ray" in …` / `return False`. Three predicates, **all Cloudflare-shaped**, and the 403 branch requires a `cf-ray` header |
| `http_status` is carried into `PageData` and **no layer or gate reads it** | `types.py:19,33`; a repo-wide grep of every non-comment `http_status` occurrence in `backend/app/**`, `backend/worker/**`, `backend/tools/**` | the **only** consumers are: `scan_tasks.py:109` (the `>=400` baseline gate), `scan_tasks.py:284` (writes it into `ScanPageData`), `cloaking.py:79` (`200 <= v.http_status < 300`, layer 7's own UA-consistency check — not a wall detector), and `fetcher.py:199` (inside the Cloudflare predicate itself). **Zero of the nine layers read it.** |

### 4.2 The measurement

```
### STEP 1 - capture_baseline() against a 200-OK Cloudflare wall
  task return        : 'ready'   in 0.14 s
  baseline.status    : ready
  baseline.error     : None
  baseline.is_current: True
  baseline.html_path : 'baselines/d2697728-2aa8-4054-9445-f95c0ff09c55/page.html'
  >>> POISONED       : True
  stored page.html (478 B) is the wall: True
  stored head: '<!doctype html><html><head><title>Just a moment...</title>\n
                <meta name="cf-browser-verification" content="sha25…'

### STEP 2 - run_scan() against the REAL page, 22.34 s later
  task return        : 'flagged'
  scan.status        : completed
  scan.verdict       : flagged
  scan.risk_score    : 0.9999999999997338
  layer_scores       : layer1 1.0 · layer2 0.6 · layer3 0.08 · layer4 0.974
                      layer5 0.0 · layer6 0.0 · layer7 DEGRADED · layer8 0.998 · layer9 1.0
  scan_findings      : 9 rows, one per layer
  MATERIAL_CHANGE_RISK=0.4  -> changed = True
  site.current_interval_minutes = 15

### CONTROL - healthy baseline, the SAME page one tick later
  capture_baseline() -> 'ready'  is_current=True
  run_scan()         -> 'changed'
  scan.risk_score    = 0.3
  site.current_interval_minutes = 22

>>> POISONED  risk=0.9999999999997338  verdict=flagged  interval=15 min
>>> CONTROL  risk=0.3                 verdict=changed  interval=22 min

### POSITIVE CONTROL - does the >= 400 guard work at all?
  HTTP 403 -> 'failed'  status=failed  is_current=False
  error='Site responded with HTTP 403 — a trusted baseline needs a healthy
         response. Try again when the site is up.'
```

**Both halves of the question, answered separately as the brief asked:**

- **The poisoning** (baseline stored junk): `capture_baseline()` returned `ready`, set `is_current=True`, and wrote a 478-byte `page.html` whose `<title>` is `Just a moment...`. The trust anchor for the site is now a Cloudflare interstitial. The `>= 400` guard works **exactly as written and nothing more** — the positive control proves it fires on 403 and refuses.
- **The consequence** (the scan flagged): the very next scan of the site's **real** content returned `verdict=flagged` at `risk_score = 0.9999999999997338`, from **4 independent layers** (1.0 / 0.6 / 0.08 / 0.974 / 0.998). The control — the *same page*, one tick later, against a healthy anchor — returned `0.3` and `changed`. **The only variable changed between the two runs is which bytes the anchor holds.**

**The compounding factor, which makes this worse than a one-off alarm.** The poisoned site **tightened its cadence to 15 minutes**; the healthy one relaxed to 22. Per Session A's `AUDIT-4B-3`, a tightened site needs **four consecutive clean scans** to recover, and while poisoned **no scan can ever be clean**. So a single poisoned baseline is a **self-sustaining, permanent** false-alert generator *and* a 4× scan-rate amplifier on exactly the site the operator is most likely to be chasing. With the poisoned site at base/4, that is ~96 scans/day instead of 24, each one a full Playwright capture plus a MiniLM pass.

**Names from the spec's own examples.** The mechanism is vendor-agnostic in the sense that matters: a DataDome 200 captcha, an Akamai or PerimeterX interstitial, an AWS WAF challenge, a paywall, or a cookie/consent wall all satisfy the same two conditions — HTTP 200, and no Cloudflare-shaped marker. I used a Cloudflare-shaped page *precisely because it is the one vendor the code claims to handle*, and it still got through: `looks_like_challenge_page` is evaluated against a **challenge-marker probe of the live DOM** (`fetcher.py:204-212`, `_CHALLENGE_PROBE_JS`) that my stub bypassed. So the honest statement of the exposure is: **the fetcher's challenge-wait does run in production and would catch a genuine Cloudflare challenge that resolves within its window; the baseline path has no *independent* wall check, so anything that survives the wait — a solved-but-still-gated page, a different vendor, a paywall, a consent wall, or a challenge that resolves *into* a "verify you are human" page — is stored as trusted.** That is a narrower and more accurate claim than "any soft block gets through", and it is the one the evidence supports.

**Severity: High.** Justification: it is a **false positive on the product's core output** (a `flagged` verdict and an alert on a healthy site), it is **self-perpetuating**, it is **silent** (no error, no log, no counter — the baseline row says `ready`), and it fires on the **default** `add site` path for any site behind a wall. It is **not Critical** on the Rule 12/§6.4 reading, because it is a *false alarm*, not a false clean: it never hides a real compromise, and the operator's response is an unnecessary investigation, not a missed breach. It is also trivially reversible by one `rebaseline_site` click — the harm is the unbounded alert volume and the burned trust, not permanent corruption.

---

## 5. `DOC-1` … `DOC-8`+

Every claim below was cross-checked against **live code and live behaviour**, never taken at face value (Rule 13).

### DOC-1 — Linked stylesheet claims: the docs describe a relation-aware collector that does not exist, and the difference is worth 0.34 of the 0.40 risk budget **[MEDIUM]**

`docs/layers/3-link-audit.mdx:22`:

```
| `link_href` | `<link href>` (stylesheets, fonts) | 0.6 |
```

`backend/worker/detection/dom.py:664-667` — the entire implementation:

```python
elif tag == "link":
    r = _norm_ref(base, el.get("href") or "")
    if r:
        refs["link_href"].add(r)
```

**`el.get("rel")` is never called.** I proved it by `inspect.getsource`: `_collect_refs` contains the substring `rel` **zero** times and `el.get("rel")` zero times. Every `<link href>` is collected regardless of its relation — `stylesheet`, `icon`, `preload`, `prefetch`, `preconnect`, `dns-prefetch`, `manifest`, `alternate`, `apple-touch-icon`, `canonical`, `search`, `help`, `next`/`prev`, everything.

Measured through the real layer, 9 cases (`layer3_link_audit` + full `run_detection`):

| change to the page | refs collected | **layer 3** | **fused risk** |
|---|---|---|---|
| `<link rel=preload href="https://newcdn.example/x.js" as="script">` (the documented attack) | 4 | **0.417** | **0.3429** |
| `<link rel=stylesheet href="https://newcdn.example/s.css">` (a real stylesheet hijack) | 4 | **0.417** | **0.3429** |
| **`<link rel=dns-prefetch href="https://fonts.gstatic.example">`** | 4 | **0.417** | **0.3429** |
| **`<link rel=preconnect href="https://cdn.jsdelivr.example">`** | 4 | **0.417** | **0.3429** |
| **`<link rel=manifest href="https://app.example/manifest.json">`** | 4 | **0.417** | **0.3429** |
| **`<link rel=alternate type="application/rss+xml" href="https://feeds.example/rss">`** | 4 | **0.417** | **0.3429** |
| **`<link rel=apple-touch-icon href="https://cdn.example/icon.png">`** | 4 | **0.417** | **0.3429** |
| `<a href="https://newsite.example/">` (documented *lowest* weight, 0.35) | 4 | 0.270 | 0.3000 |
| `<img src="https://tracker.example/pixel.gif">` (documented *not* collected) ✅ | 3 | 0.000 | 0.3000 |
| *(a new-host `<link>` **removed** from the page)* | — | **0.000** | — |

**The benign and the malicious cases are byte-for-byte indistinguishable to layer 3.** Five relation values that every modern site adds routinely — `preconnect` and `dns-prefetch` are on effectively every page that loads a third-party font or CDN — produce **exactly** the score of a genuine stylesheet hijack. The evidence for the benign case is explicit: `new_external_domain_weight: 0.6`, `total_added_refs: 1`, `added_new_domains: ['https://fonts.gstatic.example']`.

**Why 0.3429 matters even though it is below the 0.40 gate.** It is **86 % of the entire changed-verdict budget**, consumed by a single `dns-prefetch` line. The measured benign-churn floor is 0.19–0.30 (§5 DOC-2), so a `dns-prefetch` addition *plus* ordinary page churn lands squarely in `changed`, and *plus* any one of the layer-2/5 shapes reaches `flagged`. A false-positive amplifier that fires on infrastructure every site adopts is exactly the noise the adaptive cadence then reacts to (Session A's `AUDIT-4B-3` pinning), so the cost compounds twice.

**Two smaller truths in the same table:** `<img src>` is correctly **not** collected (the doc's claim there is **accurate**), and **removals score 0.0** — an attack that removes the legitimate stylesheet and injects an inline `<style>` registers as *no change at all* in layer 3. That is arguably correct (the attack is a layer-2/4/5 story) but it is not documented.

**Drift summary:** the doc's parenthetical "**stylesheets**, fonts" describes a *subset* of what is collected, and the parenthetical is the only signal a reader has that the weight 0.6 is calibrated for high-signal asset references. A `rel`-aware filter (or a doc that says "every `<link href>`, whatever its `rel`") is a one-line change on either side.

### DOC-2 — Noise floor / changed gate: three separate numeric claims, one of them right **[MEDIUM]**

| claim | location | documented value | **measured** | verdict |
|---|---|---|---|---|
| the benign fused-risk floor | `worker/scan_tasks.py:48` | "*near-zero fused risk (~0.03)*" | **0.3000** (6 benign-churn variants, screenshots present, n=6, sd=0) | **WRONG by 10×.** The claim is 10 % of the real floor. Session A independently measured 0.1907–0.2213 on its own fixture, so the honest band across two independent fixtures and two sessions is **0.19–0.30** |
| the escalation/material bar | `worker/detection/fusion.py:40` | "*can never, by themselves, cross the material-change bar / escalation floor **(0.35)** … let alone the default flag threshold (0.5)*" | `app/scanning.py:58` `MATERIAL_CHANGE_RISK = 0.4` | **WRONG.** The real bar is 0.40, not 0.35. **Independently confirmed** by reading `app/scanning.py:58` directly |
| …the same number, again | `worker/detection/fusion.py:192` | "*above the bar / escalation floor **(both 0.35)***" | 0.40 | **WRONG**, identically. Two sites, one constant, neither reads it |
| …and the actual cap | — | — | `fusion._UNMEASURED_RISK_CEIL = 0.3` | **The conclusion is *more* true than the sentence claims**: the real ceiling is 0.30, i.e. 0.10 below the 0.40 bar, not 0.05 below a 0.35 bar. The safety property holds; the arithmetic in the comment does not |
| `NOISE_FLOOR` | `worker/scan_tasks.py:59`, and `docs/detection-layers.mdx:83` | `0.02` | `ST.NOISE_FLOOR = 0.02` | **CORRECT**, and `detection-layers.mdx:86`'s "*the noise floor is verdict-only: it never touches the fused risk score*" is **also correct** (I traced it: `NOISE_FLOOR` is used only in the per-layer residue check, never in the fusion input vector) |
| `MATERIAL_CHANGE_RISK` in the docs | `docs/detection-layers.mdx:99,110` | `0.40` | `0.4` | **CORRECT.** The *docs* got this right; only the *code comments* are wrong. A useful asymmetry: `detection-layers.mdx` is the more trustworthy of the two sources |
| min observed non-skipped layer score | `worker/scan_tasks.py:58` | `0.0518` | not re-measured by me | **Session A verified this exact.** Carried forward unchanged |

**A note on my own first measurement, because getting it wrong would have produced a wrong finding.** My initial fixture had **no screenshot bytes**, which made layer 4 `degraded`, which tripped the intercept-shrinkage uplift and pinned every variant at **exactly 0.30** — I nearly reported "the benign floor is 0.30" off a measurement artifact. Re-running with real PNGs gave 0.3000 again but for a *different, legitimate* reason (a one-byte year change moves `layer1_hash` to 1.0). The two are indistinguishable from the output alone, which is why the per-layer dump is in the evidence. **The 0.19–0.30 band is the number to carry forward; a single-fixture number would be wrong.**

**Why the 0.03 claim is not cosmetic.** `NOISE_FLOOR = 0.02` is documented as sitting *below* the per-layer residue, and the comment justifies it by saying the fused risk for benign churn is "~0.03". If the real floor is 0.19–0.30, the comment's reasoning is wrong by an order of magnitude — a maintainer reading it would conclude there is ~15× more headroom between "noise" and the 0.40 gate than actually exists. Combined with DOC-1's 0.3429, **the real headroom on a modern page is not 0.37, it is 0.06.**

### DOC-3 — Telegram bot "direct DB bypass": **the diagram/claim is wrong, the code is right** **[LOW]**

**I could not find the claimed bypass in the documentation at all.** Grepped `docs/**` (all 17 `.mdx`), `docs/.mintlify/skills/wardress-operations/{SKILL.md,REFERENCE.md}` and `README.md` for `direct database|direct DB|DB bypass|bypasses|telegram.*database|Telegram.*bypass|service layer` (case-insensitive): the only hits are two unrelated `README.md`/`.mdx` security paragraphs about Fernet encryption. **There is no API-diagram claim to falsify.**

**And the code confirms Session A's determination that there is no bypass.** `worker/telegram_bot.py` is a separate process (`docker-compose.yml:142`, `command: ["python","-m","worker.telegram_bot"]`) that calls into `app/agent/tools.py`, which in turn calls `app/services.py` — the same service layer the HTTP routers use. The session surface is `ctx.surface` (`"web"` / `"telegram"`), passed as `via` into those service functions — and Session A's `AUDIT-SA3-9` proved that `via` is **silently discarded** by three of the six orchestration service functions (`create_site:198`, `trigger_scan_now:290`, `rebaseline_site:381`), each confirmed independently by `ruff ARG001`. So the *architectural* answer is clean (one service layer, one RBAC path) and the *observability* answer is that the audit log cannot tell you which surface did it for exactly those three actions.

**Verdict: the code is correct, the docs are silent rather than wrong, and the spec's premise does not match the repository as it stands.** Recording as **Low** and explicitly flagging it to the coordinator: *if a diagram exists somewhere outside `docs/` and `README.md` (a rendered image, a Notion page, a slide deck), it is not in the repository and I could not audit it.* If Session A read such a diagram, the finding should be restated as "the claim is not in the repo", not "the code contradicts the diagram".

### DOC-4 — Hop-by-hop DNS-rebinding claims: **the claim is technically true and operationally incomplete** **[MEDIUM]**

`docs/security-and-dev.mdx:13` and `README.md:422` (identical wording):

> "*To prevent SSRF bypasses via open redirects or DNS rebinding, redirect locations are checked **hop-by-hop** before fetching.*"

`README.md:422` adds: "*The same gate covers the opt-in site-favicon resolver: every outbound URL (including each redirect hop) is re-validated before any bytes are read.*"

**What I verified, without touching `app/ssrf.py` (Rule 12):** `app/ratelimit.py` is irrelevant here; the SSRF surface is `app/ssrf.py` plus `worker/ssrf_transport.py` and `worker/probe.py:95,199-205`. I read the **documentation** and checked the claims are *about* the right mechanism, and I did **not** re-derive Session A's `AUDIT-3-3` measurements (re-binding window, the 10-URLs→3-`assert_url_allowed` cache-widening root cause, the port-less cache key `f"{scheme}://{host}"` that lets `https://cdn.example.com:8443/x` inherit the verdict for `:443`). Those are Session A's to own and I am not re-litigating them.

**What the docs get wrong is the *scope of the threat*, and this is squarely mine.** "DNS rebinding" names an attack where the attacker answers the **first** resolution with a public IP and the **second** with a private one. A hop-by-hop check defeats that only if **every** resolution is validated *and* the validated address is the one actually connected to. The docs describe the former and are silent on the latter, and the phrase "*before fetching*" invites exactly the wrong reading — it describes the *ordering* of the check relative to the request, not the *binding* of the check to the socket. `docs/remediation-hooks.mdx:65` gets this **right** and is the only place in the documentation that does:

> "*Pinned fires.* When a hook fires, the worker resolves the host once and **pins the connection to the resolved address** through the same transport used for site probes - so DNS cannot silently…*"

So the codebase contains **both** a correct statement of the property and two incomplete ones. **The drift is internal**: `remediation-hooks.mdx` describes address-pinning; `security-and-dev.mdx` and `README.md` describe hop-by-hop ordering. An operator reading the security page believes they have a guarantee that the remediation-hooks page shows is a *different, stronger* guarantee. The honest fix is to make the security page say what the remediation-hooks page already says, and to state which of the two the site-probe path actually implements — **which I did not verify, and which is the single question that would settle it.** Flagged as a follow-up for whoever owns `app/ssrf.py` (Rule 12: never edited here).

### DOC-5 — Regex timeout guarantees: **the suppression claim is exactly right; the normalizer has no guarantee at all, and nothing says so** **[MEDIUM]**

**The claim** (`docs/security-and-dev.mdx:16`, `README.md:424`, identical):

> "*When filtering dynamic parts of pages using Regex-based suppression rules, the regex parser enforces a strict **2.0 second timeout limit** (`_REGEX_TIMEOUT_SECONDS`) on match evaluations to safeguard worker nodes against Catastrophic Backtracking Denial of Service attacks.*"

**Every element of this is verified correct**, which is worth stating precisely because Session A's framing ("*ReDoS immunity is not absolute*") could easily be misread as refuting it:

- `_REGEX_TIMEOUT_SECONDS = 2.0` **exists** at `worker/detection/suppress.py:38`. ✅
- It **is** enforced, at `:153` and `:155`: `compiled.sub("", el.text, timeout=_REGEX_TIMEOUT_SECONDS)` — and it is the **`regex` module** (`:28`), not stdlib `re`, so `timeout=` is real preemption rather than a no-op. ✅
- The timeout **actually fires**, and I drove it through the real `suppressed_copy` path with 800 KB of adversarial text:

| pattern | time | outcome |
|---|---|---|
| `(a\|aa)+b` | **2018.6 ms** | **bound fired** — log: `Suppression regex timed out; skipping rule: '(a|aa)+b'` |
| `(\w+\W+)*$` | **2188.3 ms** | **bound fired** |
| `^(\w+\s?)+$` · `([a-zA-Z]+)*!` · `(\d+)+#` · `([a-zA-Z0-9]+)*@` · `(https?://[a-zA-Z0-9./-]*)*!` · `(\.a[0-9]{0,10})+$` | **14.0–26.9 ms** | completed — defeated by `regex`'s optimiser, **not** by the timeout |

- The failure mode is **correct, not a crash**: `:156-163` catches `TimeoutError`, logs a warning, and appends to `supp.unusable` so the skip lands in the layer evidence ("*a suppressed signal must stay auditable, never invisible*", `:17`). ✅
- **The bound is per-rule, not per-node, and I checked the scoping carefully**: the `try` is *outside* the `for el in root.iter()` loop and *inside* the `for pattern` loop, so the **first** timing-out text node aborts that rule for the whole document. Worst case per scan is `2 sides × N rules × 2.0 s`; at `suppressed_copy` being called on both sides (`pipeline.py:146-147`), even 50 timing-out rules costs 200 s — inside the 420 s soft limit. **Correctly bounded. Not a finding.** Recording the arithmetic so the next reader does not have to re-derive it.

**So where the drift actually is — and it is a scope omission, not an error.** `worker/detection/normalize.py` runs an **automatic volatile-text pass on every scan** (`pipeline.py:148-149`, both sides) using **stdlib `re`**, module-level patterns, and **no timeout mechanism of any kind**. I probed it with 11 adversarial documents up to **1.95 MB**:

| adversarial document | size | `normalized_copy()` | raised |
|---|---|---|---|
| `two_million_chars` | 1953 KB | **136.04 ms** | — |
| `uuid_storm_1MB` | 1083 KB | 57.96 ms | — |
| `many_urls_1MB` | 1024 KB | 90.27 ms | — |
| `cache_bust_storm_1MB` | 996 KB | 73.03 ms | — |
| `huge_attr` | 488 KB | 9.75 ms | — |
| `deeply_nested` | 214 KB | 1.40 ms | — |
| `catastrophic_user_style` | 195 KB | 18.01 ms | — |
| `unicode_word` | 97 KB | 15.65 ms | — |
| `iso_bomb` | 78 KB | 7.95 ms | — |
| `unclosed_comment` | 58 KB | 8.57 ms | — |
| `classic_bomb_(a\|aa)+b` | 58 KB | 4.93 ms | — |

**Worst case 136.0 ms, 0 exceptions raised.** So the property holds today — **but by accident, not by construction.** The patterns in `normalize.py` (`_ISO_DATETIME_RE:83`, `_ISO_DATE_RE:91`, `_UUID_RE:97`, `_VOLATILE_VALUE_RE:129`, `_QUERY_PARAM_RE:132`) are all anchored or linear, and CPython's optimiser handles them. **Change any one of them to a user-influenced shape and the guarantee evaporates silently — there is no test that would fail, no timeout that would fire, and no doc that would change.** The `security-and-dev.mdx` Accordion is titled "**ReDoS Protection in Suppression Engine**" and its body says "**When filtering dynamic parts of pages using Regex-based suppression rules**" — both correctly scoped to the *suppression* engine. So the docs are not *wrong*; they are **incomplete in a way that reads as global**, and the gap is only discoverable by reading `normalize.py`.

**The accurate statement of reality, which is what the docs should say:** *ReDoS immunity is **enforced** (2.0 s, `regex` module) for user-authored suppression rules; it is **accidental but currently observed** (worst 136 ms on 1.95 MB, 0 exceptions) for the internal volatile-text normaliser, which has no timeout mechanism and no regression test pinning the property.*

### DOC-6 — Public API docs exposure: **confirmed, and Session A's two schema sizes reconcile** **[MEDIUM]**

Measured live against `http://localhost:8321`, unauthenticated, just now:

| route | status | bytes | note |
|---|---|---|---|
| `/openapi.json` | **200** | **92 500** | the full schema, unmetered, unauthenticated |
| `/docs` | 200 | 1 007 | Swagger UI |
| `/redoc` | 200 | 889 | ReDoc UI |
| **`/docs/oauth2-redirect`** | **200** | **3 012** | **Session A's 3 012 B confirmed exactly** — FastAPI's own asset route |
| `/api/openapi.json` | 404 | — | |
| `/api/docs` · `/api/redoc` | 404 | — | |
| `/api/health` | 200 | 40 | see §3.2 |

**Reconciling Session A's two numbers (92 500 vs 99 585).** I measured **92 500 B** uncompressed, matching one of the two figures exactly. The most likely explanation for 99 585 is that it was a **gzip-compressed or otherwise transfer-encoded** `Content-Length`, or was measured on an earlier commit. I did **not** reproduce 99 585 under any encoding I tried, and I am not going to guess: **the reconciliation is that 92 500 B is the live uncompressed schema size as of this session, and 99 585 B could not be reproduced.** The coordinator should keep 92 500 B as the current value and treat 99 585 B as superseded, unless a sibling can identify its provenance.

**The substantive concern Session A raised, which I confirm and which is the real reason this is a finding rather than a note.** The schema is public and unmetered, and it **narrates the SSRF gate**: it contains `allow_private_networks` as a named parameter, describes the `sitemap` fetch, and carries SSRF-related description text. So an unauthenticated caller can read a **precise, machine-readable map of the product's own security controls** — which parameter disables the private-network gate, on which routes, and what the redirect-following behaviour is. That converts a security control that currently requires guessing into one that requires only `curl`. `/docs/oauth2-redirect` being a *fourth* public route is a small confirmation that the docs surface was never enumerated deliberately.

### DOC-7 — Additional doc items **[MEDIUM]**

**7a. `TRUST_PROXY_HEADERS` — the docs omit the one word that makes the setting safe, and the omission is a security boundary.** `README.md:355`:

```
| `TRUST_PROXY_HEADERS` | `false` | Enable this *only* if Wardress is fronted by a reverse proxy. |
```

`docs/configuration.mdx:71`:

```
<ParamField path="TRUST_PROXY_HEADERS" type="boolean" default="false">
  Enable this *only* if Wardress is fronted by a reverse proxy (like NGINX).
</ParamField>
```

`app/ratelimit.py:98-106`:

```python
def client_ip(request: Request) -> str:
    """Best-effort client IP. Honors X-Forwarded-For only when the app is ...
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
```

`split(",")[0]` takes the **leftmost** value. That is correct **iff the proxy overwrites** `X-Forwarded-For`. It is **exploitable iff the proxy appends** — because the RFC 7239 de-facto convention is that proxies *append* to the right, so the leftmost entry is the one **the client supplied**. Session A proved the consequence empirically: with the documented configuration the per-IP limiter is **fully bypassable (8/8 allowed)**.

**Neither doc says the proxy must overwrite rather than append, and neither links to the relevant RFC.** NGINX's `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` — the single most common line in every NGINX reverse-proxy config, and the one a reader of "fronted by a reverse proxy (like NGINX)" is most likely to copy — **appends**. So the documentation, as written, walks the reader directly into the bypass. This is a doc-vs-security gap: the code is defensible, the docs are the defect. **Medium** (the code's default is `false`, so the bypass requires the operator to opt in; but the opt-in is exactly what the docs encourage).

**7b. `celery_app.py`'s "acknowledge late" claim is false — independently confirmed.** `worker/celery_app.py:29-30`:

```python
# Scan tasks are long-running (Playwright); acknowledge late so a
# crashed worker never silently drops a scan.
task_acks_late=True,
```

`task_acks_late` does exactly what its name says — it delays the ack — and it is a **prerequisite** for redelivery on connection loss, *not* a guarantee of it. The conf sets neither `task_reject_on_worker_lost=True` nor `task_acks_on_failure_or_timeout`, and Celery's defaults for both mean a **SIGKILLed child ACKs the message** — it is never redelivered, and recovery is the DB stale sweep up to one interval later (Session A: up to 24 h 20 min, `AUDIT-4B-5`). I confirm Phase 4B's determination. The comment should say what the setting *contributes to* and name the actual recovery primitive. **Medium**, because this comment is the natural place a future maintainer looks to understand why a lost scan is recoverable, and it points at the wrong mechanism.

**7c. CI is presented as a working safety net and is not one.** Reproduced exactly:

| CI step (`ci.yml`) | status | consequence |
|---|---|---|
| `backend:58 uv run ruff check .` | **FAILS, exit 1, `Found 9 errors`** | **the first command of the job** |
| `backend:59 ruff format --check .` | **NEVER EXECUTES** | formatting ungated |
| `backend:66 pip-audit --skip-editable` | **NEVER EXECUTES** | **dependency vulnerabilities ungated** |
| `backend:70 tools/check_torch_osv.py` | **NEVER EXECUTES** | the torch OSV cross-check — the disclosed exclusion for pip-audet's structural blindness to torch — **is not running** |
| `backend:72 pytest -q` | **NEVER EXECUTES** | **the entire backend test suite is ungated** |
| `docker:159-160 docker compose config --quiet` | runs | **neither Dockerfile is ever built in CI** |
| `walkthrough/` | **no job at all** | no audit, no lint, no typecheck, no test |
| `frontend:144 pnpm audit --audit-level high` | Session A: exit 1, 2 HIGH `undici` | frontend dependency gate red |

All 9 ruff errors are `E501 Line too long` in `backend/tools/run_stress_catalog.py:209,240,249,…`. **Honest attribution:** that file was added recently and may be a sibling's or a recent addition, so the *specific* 9 errors may be transient. **The structural conclusion is not**: a non-zero `ruff check .` on the first step of a job disables **four** subsequent gates, including the entire test suite and both dependency audits, and nothing in the workflow marks those steps `if: always()`. **This is the highest-leverage CI finding in the report** — one `continue-on-error: false` → `|| true` → step-reordering fix, or simply fixing 9 long lines, restores the whole backend gate. **Medium** (it is a *silent* loss of the entire backend safety net, which is more than cosmetic, but it is not itself an exploitable defect in the product).

**7d. `POSTGRES_DB` is in `.env.example` and in compose but in zero documentation.** Cross-referenced all 24 `.env.example` keys: `POSTGRES_DB` has `docs=0` while every other key has `docs ≥ 1`. Trivial. **Low**, recorded for completeness of the sweep.

### DOC-8 — `docs.json` navigation integrity: **clean, both directions** ✅

| check | result |
|---|---|
| nav entries (`docs/docs.json:24-76`, 5 groups) | **24** |
| `.mdx` files on disk under `docs/` | **24** |
| nav entries with **no** file | **0** |
| `.mdx` files **not** in nav (orphans) | **0** |

Exact set equality, verified programmatically. All 9 layer pages, all 3 frontend pages, and all 8 administration pages are present and reachable; nothing is stranded. The Mintlify `contextual` options (`:82-92`) and the `logo`/`favicon` paths (`:5-15`, all resolving to real files in `docs/images/`) are also consistent. **This is a verified-clean result and belongs in the ledger, not the findings.**

---

## 6. Dead code & optimisations

### 6.1 Dead code — what I found beyond Session A

| # | item | kind | proof |
|---|---|---|---|
| D1 | **`scripts/generate_structure.py`** (9 137 B, 250 lines) | **orphan script** | zero references across `scripts/*.ps1`, `README.md`, `docs/**` (incl. the Mintlify skill), `frontend/package.json`, `backend/pyproject.toml`. Not invoked by any script or workflow |
| D2 | **`GET /api/health` (readiness)** | **orphaned public route** | `docker-compose.yml:83`, `install.ps1:335`, `update.ps1:203`, `diagnostics.ps1:300` **all** use `/api/health/live`. `/api/health` has **no operational consumer anywhere**, yet is unauthenticated and returns a distinguishable 40-byte body including `"detail": "database unreachable"` |
| D3 | **`WARDDRESS_ENV` in the live `.env`** | **dead env var** | **0 references** in the entire repository (all `.py`, `.ps1`, `.yml`, `.mdx`, `.md`, `.ts`, `.tsx`, `.json`, excluding lockfiles). Also absent from `.env.example`, so `install.ps1` could not have written it — it is a hand-edit that no script will ever clean up |
| D4 | `fusion._UNMEASURED_RISK_CEIL = 0.3` | **stale constant referenced by prose only** | The name is accurate and the value is correct; what is stale is the *comment* that describes it as bounded by "0.35" (`fusion.py:40`, `:192`). Recorded under DOC-2, not here |
| D5 | `_REGEX_TIMEOUT_SECONDS`'s coverage | **half-dead guarantee** | Enforced for suppression rules (`suppress.py:153,155`); **structurally absent** from `normalize.py`, which runs on every scan. Recorded under DOC-5 |
| D6 | `lib.ps1 Quote-Arg` | **unreachable-once-fixed** | Six call sites, all fixed arg vectors, no user path. Latent Windows quoting bug (see OPS-6) |
| D7 | `uninstall.ps1:323 if ($hasTar -and $helperImage)` | **dead condition** | `$helperImage` is provably non-null whenever `$hasTar` is true, because `:134` clears the three managed filenames from a reused `-BackupPath` first |

**On Session A's 55 dead-code items (§6 of the brief asked me to verify a representative sample).** I independently re-confirmed the class representatives rather than re-litigating: `wardress.ping` (`celery_app.py:49`) — the three dead `via` parameters — `worker/db.py`'s `pool_pre_ping` — the worker's unused result backend. All consistent with Session A. **What I add is D1–D3, none of which is in the orchestration spine Session A swept**: an orphan *script* (D1), an orphan *public route* (D2), and a dead *env var on the live install* (D3). **The pattern worth naming: none of the three is dead *code* — they are all dead *entry points*.** Static analysis of function bodies would never surface any of them, because each is reachable, correct, and simply never called. That is a different detection technique (call-graph-from-the-outside plus a docs-vs-config diff) and it is the gap Session A's method left.

### 6.2 Optimisation proposals, each with a **measured** payoff

| # | proposal | target | **measured** payoff | disposition |
|---|---|---|---|---|
| **O-1** | **"Resize once per layer-4 call"** — hoist the two full-res `resize()`s, `convert("L")` the *small* image, and feed `phash`/`dhash` from the small grayscale | `worker/detection/visual.py:137-169` | **+34.3 ms / 9.5 %** at 1280×3000 (n=5+5, interleaved); **−21.9 ms / −3.6 %** at 1280×4000 (n=5+5). `sd` 50–116 ms. **The sign flips between two plausible screenshot heights.** | **INVALIDATED BY MEASUREMENT — do not do it.** The 8 resizes are 8 genuinely different operations; `cProfile` shows the real cost is `structural_similarity` + `scipy.uniform_filter1d` + PNG decode (~35 %+), not the resizes. And the `phash`/`dhash` change would alter layer-4 **evidence values**, so it is a behavioural change that would need re-validation even if it paid |
| **O-2** | **Batch the MiniLM encode calls** — one `model.encode(list_of_chunks)` per side instead of 24 individual calls | `worker/detection/semantics.py:229-232` | **261.7 ms and 1.76× per scan** (n=3, interleaved; P3 vs P4). **Corroborates Session A's 1.68× / −253 ms.** Worst case (48 calls) projects to **~523 ms**. | **VALID — the single highest-value detection optimisation available.** `SentenceTransformer.encode` already accepts a list and returns the same vectors; `_embedded_windows` would become one call plus a `list(enumerate(...))` zip. **Verify** that per-window lengths are preserved (they are — the caller only uses `len(chunk)`) and that the tokenizer's padding/truncation behaviour is identical for a batch (`max_length` is already fixed per chunk by `_EMBED_CHAR_CAP`) |
| **O-3** | **Pre-warm MiniLM in the prefork child at low priority** (`worker_process_init` hook, one `encode()` of a 1-char string), so the 19.86–54.71 s load happens at worker boot rather than inside a scan's 480 s budget | `worker/celery_app.py` | Removes **4.4–11.4 % of the hard task limit** from the first scan on every child, and staggers 12× the load off the critical path. | **VALID but a trade, not a free win.** Cost: every one of 12 children pays the load even if it never runs a scan (a fleet that mostly idles pays 12× for nothing), and the load becomes part of worker *startup* rather than lazy. The right shape is to make it **configurable** (e.g. only pre-warm when `concurrency × expected_scans_per_hour` justifies it) |
| **O-4** | **Process-scoped DB engine per prefork child**, pinned `pool_size=1, max_overflow=0` | `worker/db.py:14-22` | **89.74 ms saved per Celery task, 17.9×** (n=5, P22 vs P23; Session A: 81 ms / 13×). At ~2 400 tasks/day ≈ **215 s/day**. | **VALID, with Session A's mandatory caveat:** `size=5, max_overflow=10` per child × 12 children = 180 > `max_connections=100`, so the `pool_size=1` pin is **not optional**. The 27/100 arithmetic is only safe *because* each task uses exactly one connection on a disposable pool |
| **O-5** | **Filter `<link>` by `rel` in `_collect_refs`** — collect `stylesheet`/`preload as=style` at 0.6, demote `preconnect`/`dns-prefetch`/`manifest`/`icon`/`alternate` to ~0.05, or drop them | `worker/detection/dom.py:664-667` | **Recovers 0.34 of the 0.40 risk budget** on any page that adopts a preconnect (measured: 0.3429 → ~0.30, i.e. back to the benign floor). | **VALID and cheap** (one `elif` + a weight table). **But it is a detection-behaviour change**, so it belongs with Phase 8's false-positive work, not with a performance pass. Flagged to the coordinator for routing |
| **O-6** | **Cap `layer4`'s `MAX_COMPARE_HEIGHT` interaction** — `_common_size` clamps to 4 096 px, and for a 1280×4000 screenshot the compare is 683×2134; SSIM's cost is O(W·H) | `worker/detection/visual.py:47,75-82` | Measured 362 ms (1280×3000) → 610 ms (1280×4000): **+68 % for +33 % height**, i.e. slightly super-linear. Halving `COMPARE_WIDTH` would roughly quarter the SSIM cost. | **NOT RECOMMENDED without an accuracy measurement** — it changes what layer 4 can see, which is a detection-quality decision, not a performance one. Recorded as an option, not a proposal |
| **O-7** | **Give `update.ps1` a real `.env` reconciliation pass** — add keys present in `.env.example` but absent from `.env`, with a non-empty `CHANGE_ME` placeholder, and report (not silently apply) | `scripts/update.ps1` | Prevents the measured 14-key drift on the live install and converts a future newly-required key from a boot failure into a printed instruction. | **VALID.** The tricky part is the *default* question: a key with a non-`CHANGE_ME` default must be added **commented out**, not set, or the script silently overrides an operator's later choice. This is the same design `install.ps1` already uses for generation and should share the helper |

### 6.3 Optimisation proposals carried from Session A that I re-measured

| Session A proposal | My independent measurement | Status |
|---|---|---|
| O-SA-2 batched MiniLM | 261.7 ms / 1.76× (n=3) | **CORROBORATED** → O-2 |
| O-SA-3 resize once per layer-4 | +34.3 ms @1280×3000, **−21.9 ms @1280×4000** (n=5+5) | **INVALIDATED** → O-1 |
| O-SA-7 process-scoped DB engine | 89.74 ms / 17.9× (n=5) | **CORROBORATED** → O-4 |
| O-SA-4 event-driven banner wait (−3.09–3.14 s) | not re-measured (capture-side, W1-A's territory) | **not re-litigated** |
| O-SA-5 parallel `probe_site` UA fetches | not re-measured | **not re-litigated** |
| O-SA-6 route-level `lazy()` | not re-measured (frontend, W1-A/Session A territory) | **not re-litigated** |

---

## 7. Findings

### [NEW] AUDIT-9-1 — A 200-OK soft-block becomes a permanent, self-amplifying false-alert generator
- **Severity**: **High**
- **Subsystem / file(s)**: `backend/worker/scan_tasks.py:105-119` (the `http_status >= 400` baseline gate), `backend/worker/scan_tasks.py:280-292` (the scan path, which has **no** such gate at all), `backend/worker/fetcher.py:187-201` (`looks_like_challenge_page` — Cloudflare markers only), `backend/worker/detection/types.py:19,33` (`http_status` carried, read by no layer), `backend/app/scanning.py:58` (`MATERIAL_CHANGE_RISK = 0.4`), `backend/worker/scan_tasks.py:407-420` (`_schedule_next`, the cadence response)
- **Reproduction**: Driven through the **real** `capture_baseline` and `run_scan` task bodies against a dedicated scratch DB, with only `fetch_page`/`probe_site` stubbed.
  1. `capture_baseline(<id>)` against a site serving a 200-OK Cloudflare interstitial → returns **`'ready'`**, `baseline.status=ready`, `baseline.is_current=True`, `error=None`, and a stored `page.html` whose `<title>` is `Just a moment...` (478 B). **POISONED = True.**
  2. `run_scan(<id>)` against the site's **real** content, 22.34 s later → returns **`'flagged'`**, `verdict=flagged`, `risk_score=0.9999999999997338`, `changed=True`, 9 `scan_findings` rows, and the site's cadence **tightened to 15 minutes**.
  3. **Control**: healthy anchor, the *same* page one tick later → `risk_score=0.3`, `verdict=changed`, cadence relaxed to 22 min. The only variable is which bytes the anchor holds.
  4. **Positive control**: HTTP 403 → `'failed'`, `is_current=False`, error = "*Site responded with HTTP 403 — a trusted baseline needs a healthy response*". The `>= 400` guard works exactly as written, and nothing more.
- **Root cause**: The baseline trust anchor is gated **solely** on `http_status >= 400` (`scan_tasks.py:109`). Any wall that answers 200 bypasses it entirely. The only wall detection in the codebase is `looks_like_challenge_page`, whose three predicates are all Cloudflare-shaped (`has_challenge_marker`, `is_challenge_title`, `403 + cf-ray` header) and which is evaluated against a live-DOM probe in the **fetch** path — so anything the challenge-wait does not resolve *within its window* (a different vendor, a paywall, a consent wall, a solved-but-still-gated page) is stored as trusted. And `http_status` is carried into `PageData`/`ScanPageData` where **no layer and no gate reads it**, so downstream detection has no opportunity to notice. The **scan** path (`scan_tasks.py:280-292`) has no status gate at all, which is why a fetch that hits a wall mid-scan produces a legitimate-looking scan rather than a failure.
- **Why High and not Critical**: it is a *false positive* on the core output, not a false clean — a real compromise is never hidden. It is not cosmetic: it is silent (the baseline row says `ready`), self-perpetuating (per Session A's `AUDIT-4B-3` a tightened site needs 4 consecutive clean scans to recover, and a poisoned site can never produce one), and it *multiplies* load (base/4 = ~96 scans/day instead of 24, each a full capture + MiniLM pass). Reversible by one `rebaseline_site` click. Not Critical per §6.4.
- **Proposed remedy category**: input-validation gate + detection-layer input; and a threshold/adaptive response so a site whose anchor is suspect is not auto-tightened.
- **Source**: new (PROMPT-003 Phase 9, `NB-CAP-2`)

### [NEW] AUDIT-9-2 — `update.ps1` never reconciles `.env` with `.env.example`; the live install has already drifted 14 documented keys
- **Severity**: **High**
- **Subsystem / file(s)**: `scripts/update.ps1:31,63-65,189-191,218` (all five `.env` references — none writes), `scripts/install.ps1:8-10,188,236,247-254` (generation is first-run-only and never merges), `backend/app/config.py:86` + `backend/app/ratelimit.py:129` (`login_rate_limit_per_ip`), `docker-compose.yml:39-71` (the `${VAR:-default}` vs `${VAR:?}` split), `.env.example` (24 keys) vs the live `.env` (11 keys)
- **Reproduction**: (a) grep `\.env` across `scripts/*.ps1` → 49 matches in 4 files; the **only** `.env` **write** in the entire script set is `install.ps1:236`, inside `if ($FirstInstall)`. `update.ps1:17` states in its own header that `.env` is "*never touched*". (b) Diff the key sets of the live `.env` against `.env.example` → **14 of 24 documented keys absent**, and **1 key present in neither the docs nor the code** (`WARDDRESS_ENV`, 0 repo-wide references). (c) `docker compose config | Select-String LOGIN_` → 0 hits; `docker inspect wardress-app-1` env names → 26 variables, none `LOGIN_RATE_LIMIT_PER_IP`.
- **Root cause**: The design deliberately treats `.env` as write-once-at-first-install ("*Idempotent: an existing .env is NEVER touched*", `install.ps1:10`) and `update.ps1` inherits that, so there is **no reconciliation pass on any upgrade**. The consequence set is: documented knobs silently fall back to compose defaults (`RATE_LIMIT_PER_IP`, `TRUST_PROXY_HEADERS`); a future `${VAR:?}` key turns an upgrade into a **boot failure** naming a key the operator has never heard of; and a changed default leaves an upgraded install permanently on the old value. `LOGIN_RATE_LIMIT_PER_IP` is the sharpest case: a pydantic-defaulted, exercised, security-relevant knob that appears in **neither** `.env.example` **nor** compose, and is therefore **unsettable through `.env`** — an operator who adds it gets a silent no-op.
- **Why High**: an operator-harming script defect that has *already silently degraded the live install*. Not Critical because the loud failure class fails closed and no data is at risk.
- **Proposed remedy category**: configuration-management / upgrade-time migration of the operator's own config file, with a non-destructive report mode.
- **Source**: new (PROMPT-003 Phase 9, `OPS-1`)

### [NEW] AUDIT-9-3 — `validate.ps1` green-lights a memory configuration the measured deployment cannot survive, and never checks disk or ports
- **Severity**: **High**
- **Subsystem / file(s)**: `scripts/validate.ps1:185-217` (the resource check), `scripts/install.ps1` (no Node check, no port check, no disk check), `docker-compose.yml:89-116` (no limits, no healthcheck), `backend/Dockerfile.worker:36` (no `-c`)
- **Reproduction**: Replayed `validate.ps1`'s exact arithmetic against the live engine: `docker info --format json` → `MemTotal = 7 976 714 240`; `[math]::Round(7976714240/1GB,1)` = **7.4**; `7.4 -lt 4` = **`False`** → **no warning emitted**. Grep for `Disk|Get-PSDrive|port|Listen|NetTCP|8321` in `validate.ps1` → **0 hits**. Host total RAM **15.34 GiB**, free **4.46 GiB** — so Docker is capped at **48 %** of the machine and `validate.ps1` never says so. Against Session A's measured **5.90 GiB** for 12 warm children (**79 %** of that 7.43 GiB ceiling) with a **624.5 MB non-reclaimable** per-child floor and **no `-c`** (so concurrency defaults to `os.cpu_count()=12`).
- **Root cause**: The check reads `docker info`'s `MemTotal` — the **VM ceiling** — and compares it to a **4 GB** threshold framed as a *build-speed* concern. It never relates the ceiling to the host's RAM, never expresses the requirement in the unit that actually binds (concurrent warm children), and never checks the two resources that fail *after* a multi-minute serial build (disk space, port 8321 free). `diagnostics.ps1:372` warns at < 10 GB free — the diagnostics script checks a resource the pre-install validator does not.
- **Why High**: the brief's own rule ("*a `validate.ps1` that green-lights a configuration the measured deployment cannot survive*"). The consequence is not cosmetic: the failure mode it cannot see is an OOM-looping-but-alive worker, which `restart: unless-stopped` never restarts and the absent healthcheck (D2) never reports.
- **Proposed remedy category**: preflight resource validation with a threshold expressed in the deployment's real unit; add the missing disk and port checks.
- **Source**: new (PROMPT-003 Phase 9, `OPS-2`, `OPS-3`)

### [NEW] AUDIT-9-4 — `diagnostics.ps1` does not scrub the product's own `wk_` API keys; 9 of 16 hostile shapes escape a bundle the script tells the user is safe to share
- **Severity**: **High**
- **Subsystem / file(s)**: `scripts/diagnostics.ps1:30-66` (`Get-SecretScrubbers`), `:68-73` (`Protect-Line`), `:207-222` (five containers' logs, captured verbatim), `:141` (`docker info`, verbatim), `:395` (the "*safe to share*" footer), `backend/app/apikeys.py:13-21` (`API_KEY_PREFIX = "wk_"`, `raw = "wk_" + secrets.token_urlsafe(32)`)
- **Reproduction**: `Get-SecretScrubbers` and `Protect-Line` copied **verbatim** into a scratch harness with `$RepoRoot` repointed at a **synthetic** `.env` fixture (the real `.env` was never read; no live credential entered the harness, the transcript, or this report). 16 hostile-shaped probes → **`scrubbed=7 escaped=9`**. Escaped verbatim: `wk_` key in a `Bearer` header / in a query string / in a JSON error body; a JWT (`eyJ….….…`); a Fernet key (`gAAAAA…`); a Telegram bot token shape; an Apprise URL with an embedded credential; a `postgresql://user:pass@host/db` literal; a bare base64 blob. Scrubbed: `sk-`, `AKIA`, `xoxb-`, `ghp_`, and the 3 `.env` values present in the fixture.
- **Root cause**: the generic rule list is a **four-entry allowlist of third-party token shapes** (`sk-`, `xox[baprs]-`, `gh[pousr]_`, `AKIA`) plus exact-value rules for **six** `.env` keys — with **no default-deny** and **no rule for `wk_`**, the format the product itself issues. A secondary ordering bug: `POSTGRES_PASSWORD` is applied at index 0 and `DATABASE_URL` at index 1, so the password rule rewrites the URL first, the `DATABASE_URL` rule no longer matches, and the **host, port, database name and username survive** — demonstrating the rule set was never tested against a composition of its own inputs.
- **Why High**: a false "clean" in an artefact the script explicitly invites the user to attach to a public issue. Not Critical: no code path in the files I read logs a full `wk_` key in steady state, so the exposure requires a future log-echo path; the finding is that the safety net is **absent and advertised as present**.
- **Proposed remedy category**: redaction policy change — default-deny with an explicit per-format allowlist including the product's own key format, plus a regression test over a hostile corpus.
- **Source**: new (PROMPT-003 Phase 9, `OPS-4`); related precedent Session A `AUDIT-4E-8` (High)

### [NEW] AUDIT-9-5 — The documented restore path silently downgrades the schema below the running binary, and reports success on a partial load
- **Severity**: **High**
- **Subsystem / file(s)**: `scripts/uninstall.ps1:288-330` (`RESTORE.txt` generation), `:319-322` (the `psql -f` restore step), `:251-284` (the artifacts archive, and its non-`$missing` failure path at `:282-284`), `:52,141-147,370-375` (the hardcoded `$Project` and the two non-`$missing` skip paths), `:207-233` (the dump sanity check that the restore half lacks)
- **Reproduction** (static analysis per Rule 15; `uninstall.ps1` was **not run**): read `RESTORE.txt`'s generated steps and cross-check them bidirectionally against what the backup produces. (a) Step 2 runs `install.ps1` → `alembic upgrade head`; step 3 replays the dump with `pg_dump --clean --if-exists`, reverting the schema to the backup's vintage; step 5 starts the stack. **There is no `alembic upgrade head` after the load.** (b) The restore step is `docker compose exec -T db psql … -f /tmp/restore.sql`; `psql`'s default is `ON_ERROR_STOP` **off**, so it continues past errors and **exits 0**, and `docker compose exec` propagates 0. (c) `$Project = "wardress"` is hardcoded (`:52`) while Compose honours `COMPOSE_PROJECT_NAME` from the same `.env`; on a mismatch, `:254` inspects the wrong volume, `:282-284` prints a yellow line and **does not add to `$missing`**, the completeness check reports success, and `:356` then destroys the volume. (d) A missing `.env` (`:141-147`) is likewise not recorded in `$missing` — yet the DB dump's Fernet-encrypted SMTP/Telegram/Apprise/AI credentials are **undecryptable** without it.
- **Root cause**: the backup/restore pair is written in two halves with different standards. The **write** half is careful to the point of being exemplary (byte-exact `docker compose cp` with a comment explaining the UTF-16LE re-encoding hazard; a `--`-prefix sanity check on the dump; a per-component `$missing` ledger that **stops the script before deleting anything**, with a dedicated `-AllowIncompleteBackup` and `exit 2`). The **read** half omits the migration step, omits `ON_ERROR_STOP`, and — because `$Project` and the "component absent" case are treated as *absent* rather than *failed* — a whole class of loss exits **0**.
- **Why High**: three distinct silent-data-loss or silent-misconfiguration paths in the officially documented recovery procedure, two of which (a, c) destroy or strand operator data. Not Critical: no live path was executed, and the static conclusion for (b)/(c) is a code-trace with high but not measured confidence — see §2.
- **Proposed remedy category**: transactional/ordering correctness in the documented recovery procedure; treat "absent" as "failed" for components whose absence is unrecoverable; fail-closed error propagation from the restore commands.
- **Source**: new (PROMPT-003 Phase 9, `OPS-5`). **Confidence: medium-high static; the end-to-end replay is UNVERIFIED** because Rule 15 forbids running the scripts.

### [NEW] AUDIT-9-6 — Every `<link href>` is scored at 0.6 regardless of its `rel`, so five routine relations are indistinguishable from a stylesheet hijack
- **Severity**: **Medium**
- **Subsystem / file(s)**: `backend/worker/detection/dom.py:640-676` (`_collect_refs`; `el.get("rel")` is never called), `:696` (`new_domains_weighted`), `docs/layers/3-link-audit.mdx:22` ("`link_href` | `<link href>` (stylesheets, fonts) | 0.6`")
- **Reproduction**: `inspect.getsource(_collect_refs)` → contains `rel` **0** times. Then 9 cases through the real `layer3_link_audit` and the full `run_detection`:

| change | layer 3 | fused risk |
|---|---|---|
| `<link rel=preload href="https://newcdn.example/x.js" as="script">` | 0.417 | 0.3429 |
| `<link rel=stylesheet href="https://newcdn.example/s.css">` | 0.417 | 0.3429 |
| **`<link rel=dns-prefetch href=…>`** | **0.417** | **0.3429** |
| **`<link rel=preconnect href=…>`** | **0.417** | **0.3429** |
| **`<link rel=manifest href=…>`** | **0.417** | **0.3429** |
| **`<link rel=alternate type="application/rss+xml" href=…>`** | **0.417** | **0.3429** |
| **`<link rel=apple-touch-icon href=…>`** | **0.417** | **0.3429** |
| `<a href>` to a new host | 0.270 | 0.3000 |
| `<img src>` to a new host | 0.000 | 0.3000 ✅ (doc correct) |
| a new-host `<link>` **removed** | **0.000** | — |

  Evidence dict for the `dns-prefetch` case: `{'link_href': {'added': ['https://fonts.gstatic.example'], 'added_new_domains': ['https://fonts.gstatic.example']}, 'new_external_domain_weight': 0.6, 'total_added_refs': 1}`.
- **Root cause**: the collector is relation-blind, so the 0.6 weight — calibrated for a high-signal asset reference — is applied to `preconnect`/`dns-prefetch`/`manifest`/`icon`/`alternate`, which are infrastructure every modern site adopts. The documentation's parenthetical "*(stylesheets, fonts)*" is the only signal a reader has that the weight is relation-calibrated, and it describes a subset of what is collected.
- **Why Medium and not High**: 0.3429 is **below** the 0.40 changed gate on its own, so it does not produce a false `changed` by itself. It is Medium because it consumes **86 % of the entire changed-verdict budget** on a routine line, so it converts ordinary churn (measured benign floor 0.19–0.30) into `changed`, and — via the adaptive cadence — into permanent `base/4` pinning. Two smaller true statements: `<img src>` is correctly excluded (the doc is right), and **removals score 0.0**, which is undocumented.
- **Proposed remedy category**: detection-layer input filtering + a weight table; **route to Phase 8** (detection accuracy) rather than a performance pass, because it is a behavioural change.
- **Source**: new (PROMPT-003 Phase 9, `DOC-1`)

### [NEW] AUDIT-9-7 — Three code comments assert a 0.35 material-change bar; the constant is 0.40, and the benign-risk comment is 10× off
- **Severity**: **Medium**
- **Subsystem / file(s)**: `backend/worker/detection/fusion.py:40` ("*the material-change bar / escalation floor **(0.35)** … let alone the default flag threshold (0.5)*"), `backend/worker/detection/fusion.py:192` ("*the bar / escalation floor **(both 0.35)***"), `backend/worker/scan_tasks.py:48` ("*near-zero fused risk **(~0.03)** — the classic … 'changed' on every scan*"), `backend/worker/scan_tasks.py:59` (`NOISE_FLOOR = 0.02`), `backend/app/scanning.py:58` (`MATERIAL_CHANGE_RISK = 0.4`), `backend/worker/detection/fusion.py` (`_UNMEASURED_RISK_CEIL = 0.3`)
- **Reproduction**: 6 benign-churn variants (rotating nonce, year, and hyphenation) with real 1280×1400 PNGs, through the real `run_detection`: fused risk = **[0.3000 × 6]**, band **0.3000–0.3000**, sd 0. Session A independently measured **0.1907–0.2213** on its own fixture. `app/scanning.py:58` read directly → **0.4**. `NOISE_FLOOR` → 0.02. `_UNMEASURED_RISK_CEIL` → 0.3. Per-layer dump for a benign variant: `layer1_hash 1.0, layer2 0.0, layer3 0.0, layer4 0.0048, layer5 0.0, layer6 DEGRADED, layer7 DEGRADED, layer8 0.0, layer9 0.30`.
- **Root cause**: the numeric assertions in the fusion docstring were never re-derived when `MATERIAL_CHANGE_RISK` moved 0.35 → 0.40, and the noise-floor justification quotes a fused-risk figure that is an order of magnitude below anything observable. A maintainer reading `scan_tasks.py:48` would conclude ~15× more headroom exists between noise and the gate than actually exists.
- **Why Medium**: comment/constant drift, no behavioural defect — the *code* is right. The honest band across two independent fixtures and two sessions is **0.19–0.30**, and the useful correction is that the *conclusion* of `fusion.py:40` is **stronger** than its arithmetic: the real ceiling is 0.30, i.e. 0.10 below the 0.40 bar, not 0.05 below a 0.35 bar. Note the **docs are more accurate than the code comments here** — `docs/detection-layers.mdx:99,110` state 0.40 correctly.
- **Proposed remedy category**: comment/constant correction; optionally pin the claims with a named test so they cannot drift again.
- **Source**: Session A's DOC-2 item, independently re-measured and extended with the `_UNMEASURED_RISK_CEIL` reconciliation

### [NEW] AUDIT-9-8 — The ReDoS guarantee is enforced for user suppression rules, absent for the normaliser that runs on every scan, and the docs read as global
- **Severity**: **Medium**
- **Subsystem / file(s)**: `backend/worker/detection/suppress.py:38,143-163` (`_REGEX_TIMEOUT_SECONDS = 2.0`, `compiled.sub(..., timeout=…)`, the `TimeoutError` → `supp.unusable` path), `backend/worker/detection/normalize.py:83,91,97,129,132` (stdlib-`re` patterns, no timeout), `backend/worker/detection/pipeline.py:144-150` (the normaliser runs on both sides of every non-gated scan), `docs/security-and-dev.mdx:15-18`, `README.md:424`
- **Reproduction**: (a) **Suppression half, VERIFIED CORRECT** — `_REGEX_TIMEOUT_SECONDS = 2.0` exists at `suppress.py:38` and is passed to `regex.compile(...).sub(..., timeout=2.0)` at `:153,155`. Driven through the real `suppressed_copy` with 800 KB of adversarial text: `(a|aa)+b` → **2018.6 ms**, log `Suppression regex timed out; skipping rule: '(a|aa)+b'`; `(\w+\W+)*$` → **2188.3 ms**, same. Six other classic bombs → **14.0–26.9 ms** (defeated by `regex`'s optimiser, *not* by the timeout). 0 unhandled exceptions. Scope check: the `try` is outside the node loop and inside the pattern loop, so worst case is `2 sides × N rules × 2.0 s` — bounded and inside the 420 s soft limit. (b) **Normaliser half, NO GUARANTEE** — 11 adversarial documents up to **1.95 MB** through the real `normalized_copy()`: worst **136.04 ms**, 0 exceptions raised. Stdlib `re`, module-level patterns, **no timeout mechanism of any kind, and no test pinning the property**.
- **Root cause**: the two regex subsystems were built at different times with different threat models. The user-facing one got an enforced bound via the `regex` module; the internal one got none, and its safety is an emergent property of its patterns being anchored and linear. The Accordion title ("*ReDoS Protection in Suppression Engine*") and body ("*When filtering dynamic parts of pages using Regex-based suppression rules*") are both **correctly scoped** — the drift is that a reader takes a globally-worded security guarantee from a page that also states the 2.0 s figure, and the internal normaliser is invisible from the docs entirely.
- **Why Medium**: no current defect (worst measured 136 ms) and the property is real today. It is Medium because the guarantee is **unenforced and unpinned** for a code path that runs on **every scan**, so a single future pattern edit erases it with no failing test, no timeout, and no doc change — and because the page's framing invites the reader to believe otherwise.
- **Proposed remedy category**: enforcement (a bound or a fuzz regression test) for the internal regex path; scope wording in the security page.
- **Source**: new (PROMPT-003 Phase 9, `DOC-5`); corrects the scope of Session A's "ReDoS immunity is not absolute" so it is not misread as refuting a correct claim

### [NEW] AUDIT-9-9 — The entire backend CI gate is dead behind a 9-error `ruff check .`
- **Severity**: **Medium**
- **Subsystem / file(s)**: `.github/workflows/ci.yml:56-72` (backend job: `ruff check .` at `:58`, then `ruff format --check` `:59`, `pip-audit` `:66`, `check_torch_osv.py` `:70`, `pytest -q` `:72`), `:154-165` (docker job: `docker compose config --quiet` only), `backend/tools/run_stress_catalog.py:209,240,249,…` (the 9 `E501`s)
- **Reproduction**: `uv run --frozen ruff check .` from `backend/` → **`Found 9 errors`**, exit 1, all `E501 Line too long`, all in `backend/tools/run_stress_catalog.py`. Since `ruff check .` is the **first** command of the backend job, `ruff format --check`, `pip-audit --skip-editable`, `tools/check_torch_osv.py` and `pytest -q` **never execute**. `ci.yml:159-160` shows the docker job runs **only** `docker compose config --quiet` — **neither Dockerfile is ever built**. No job references `walkthrough/` at all. Session A additionally measured `pnpm audit --audit-level high` at exit 1 with 2 HIGH `undici`.
- **Root cause**: GitHub Actions steps in a job short-circuit on the first non-zero exit and no step is marked `if: always()`. A file recently added to the tree put the linter over its line-length limit, which silently converted a five-gate backend job into a single-gate job.
- **Honest attribution**: the 9 errors are all in one recently-added file and may be transient. **The structural conclusion is not** — a non-zero `ruff check .` on step 1 disables four downstream gates including the whole test suite and both dependency audits, and nothing marks that coupling.
- **Why Medium**: a silent loss of the entire backend safety net, which is more than cosmetic, but it is not itself an exploitable product defect and the *disclosed intent* of the workflow is correct.
- **Proposed remedy category**: CI pipeline ordering/robustness — decouple the gates so one cannot mask the rest, and restore the intended line-length compliance.
- **Source**: new (PROMPT-003 Phase 9, `DOC-7c`); Session A's CI item reproduced exactly (same 9 errors)

### [NEW] AUDIT-9-10 — Three dead entry points the code-walking method cannot reach
- **Severity**: **Low**
- **Subsystem / file(s)**: `scripts/generate_structure.py` (9 137 B, 250 lines, no callers), `backend/app/routers/health.py:64-70` (the `/api/health` readiness route, no operational consumer), `.env` (live) line `WARDDRESS_ENV`
- **Reproduction**: (a) grep `generate_structure` across `scripts/*.ps1`, `README.md`, `docs/**` (incl. the Mintlify skill), `frontend/package.json`, `backend/pyproject.toml` → **0 references**. (b) `GET http://localhost:8321/api/health` → **200, 40 bytes**, unauthenticated, returns a distinguishable body including `"detail": "database unreachable"`; while `docker-compose.yml:83`, `install.ps1:335`, `update.ps1:203` and `diagnostics.ps1:300` **all** use `/api/health/live`. (c) grep `WARDDRESS_ENV` across every `.py`/`.ps1`/`.yml`/`.mdx`/`.md`/`.ts`/`.tsx`/`.json` in the repo (excluding lockfiles) → **0 references**; and it is absent from `.env.example`, so `install.ps1` could not have written it.
- **Root cause**: these are all **entry points**, not routines. Each is reachable, correct, well-formed, and simply never called — so no amount of inspecting function bodies, unused-import analysis, or `ruff ARG/F401/F841` finds them. Detecting them requires (i) a call-graph rooted at the *outside* (what do the scripts, the compose file and the browser actually invoke?) and (ii) a three-way diff of `.env.example` × `.env` × `docker-compose.yml`. That is a different technique from the one Session A used, and it is the gap worth naming for the remediation phase.
- **Severity: Low** — zero behavioural impact individually. (b) has a security flavour — an unauthenticated, unmetered, distinguishable oracle for database liveness — which is why it is folded into `AUDIT-9-13` rather than standing alone.
- **Proposed remedy category**: dead-surface inventory via an outside-in call graph; decide per item whether to delete, wire, or document.
- **Source**: new (PROMPT-003 Phase 9) — **beyond** Session A's 55 items

### [NEW] AUDIT-9-11 — `beat` still declares no `depends_on: db`, and three of seven services have no healthcheck
- **Severity**: **Medium**
- **Subsystem / file(s)**: `docker-compose.yml:129-131` (beat's `depends_on` = redis only), `:89-116` (worker: no healthcheck), `:118-131` (beat: no healthcheck), `:136-162` (telegram-bot, ollama: no healthcheck), `backend/app/routers/health.py:123-134` (the Redis key the health page already reads)
- **Reproduction**: full read of the 168-line compose file. Healthcheck blocks exist at exactly three lines: **17 (db), 28 (redis), 82 (app)**. `beat` does receive `DATABASE_URL` (`:125`) and therefore does import `worker.db`, so the missing edge is a *declaration* gap, not a "beat doesn't need the DB" case. Four of the five beat tasks require Postgres. `docker inspect wardress-beat-1 --format '{{json .Mounts}}'` → `[]` (the schedule-file note, §3.4).
- **Root cause**: each service's `depends_on` and healthcheck block was written when that service was added, and nothing has revisited them. The single failure mode the stack cannot observe — an OOM-looping-but-alive worker (Session A `AUDIT-4B-7`, 624.5 MB/child non-reclaimable, 5.90 GiB at 12 children) — is invisible to Docker, to `docker compose ps`, and to `restart: unless-stopped`, which only restarts a container that *exits*.
- **Note**: I confirm Session A's `AUDIT-SA3-7` and add the third and fourth missing healthchecks, plus the observation that **the existing `app` healthcheck is correct** (it targets `/api/health/live`, the no-DB liveness route, and `curl` is present in the image: `/usr/bin/curl` 8.14.1) — so `AUDIT-SA4-9`'s false-healthy-readiness problem does **not** propagate to Docker's view of the stack.
- **Proposed remedy category**: compose topology — add the missing dependency edge and the missing healthchecks.
- **Source**: Session A `AUDIT-SA3-7` re-verified and extended

### [NEW] AUDIT-9-12 — `TRUST_PROXY_HEADERS` is documented without the one condition that makes it safe
- **Severity**: **Medium**
- **Subsystem / file(s)**: `README.md:355`, `docs/configuration.mdx:71`, `backend/app/ratelimit.py:98-106` (`forwarded.split(",")[0].strip()`)
- **Reproduction**: read all three. The code takes the **leftmost** `X-Forwarded-For` entry, which is correct **iff the proxy overwrites** and exploitable **iff the proxy appends** (the de-facto convention, and NGINX's default `proxy_add_x_forwarded_for`). Neither doc says which is required, and `configuration.mdx` names NGINX as the example — the proxy whose default line is the appending one. Session A measured the consequence end to end: with the documented configuration the per-IP limiter is **fully bypassable (8/8 allowed)**.
- **Root cause**: the doc describes *when* to enable the flag ("*only if Wardress is fronted by a reverse proxy*") and not *what the proxy must then do*. The default is `false`, so the code is defensible; the documentation is the defect, because it walks the reader into the bypass.
- **Why Medium**: the bypass requires the operator to opt in — but the opt-in is exactly what the docs encourage, and a rate limiter that can be bypassed with one header is a security boundary, not a tuning knob.
- **Proposed remedy category**: documentation of a security-relevant precondition (overwrite-vs-append), ideally with a reference configuration snippet.
- **Source**: new (PROMPT-003 Phase 9, `DOC-7a`)

### [NEW] AUDIT-9-13 — `/api/health` is an orphaned public route that discloses database liveness, and its docstring advertises a compose healthcheck that no longer exists
- **Severity**: **Medium**
- **Subsystem / file(s)**: `backend/app/routers/health.py:1-13` (module docstring), `:64-70` (the route and its docstring: "*Backward-compatible with the Phase 0 compose healthcheck, which curls /api/health*"), `docker-compose.yml:83` (which curls `/api/health/**live**`")
- **Reproduction**: `GET http://localhost:8321/api/health` → **200, 40 bytes**, unauthenticated. `docker-compose.yml:83` read directly: `test: ["CMD","curl","-sf","http://localhost:8000/api/health/live"]`. Four operational call sites (`install.ps1:335`, `update.ps1:203`, `diagnostics.ps1:300`, and compose itself) all use `/live`. So the route has **no operational consumer**, returns `200` in *both* branches (Session A `AUDIT-SA4-9`), and the DB-down branch adds `"detail": "database unreachable"`.
- **Root cause**: the route was the Phase 0 healthcheck target; the healthcheck was later moved to `/live` (correctly, to avoid `AUDIT-SA4-9`), and the route's docstring was never updated. The consequence is a leftover public endpoint that (a) has no operator, (b) cannot be used as a status-code probe because it is 200 either way, and (c) *can* be used as a content-based oracle for "is the database up" by an unauthenticated caller — free, unmetered reconnaissance that helps an attacker choose between a DB-credential attack and something else.
- **Why Medium**: it discloses one boolean to an unauthenticated caller and has no write path. Not High: a single liveness bit, no data, no state change.
- **Proposed remedy category**: either delete the orphaned route or give it a real contract (a correct status code, no unauthenticated detail) and a real consumer; fix the docstring either way.
- **Source**: Session A `AUDIT-4C-5`, independently confirmed and extended with the "no operational consumer at all" observation. **Rule 12 honoured**: `app/ssrf.py` was not read-modified and no SSRF change is proposed here.

### [NEW] AUDIT-9-14 — `celery_app.py`'s "acknowledge late so a crashed worker never silently drops a scan" is false
- **Severity**: **Medium**
- **Subsystem / file(s)**: `backend/worker/celery_app.py:29-30` (the comment), `:31` (`task_acks_late=True`), `:44-45` (`task_soft_time_limit=420`, `task_time_limit=480`); no `task_reject_on_worker_lost` / `task_acks_on_failure_or_timeout` anywhere in the file
- **Reproduction**: read the comment and the surrounding conf. `task_acks_late` delays the ack, which is a **prerequisite** for redelivery on connection loss — not a guarantee of it. Neither `task_reject_on_worker_lost=True` nor `task_acks_on_failure_or_timeout=True` is set, and Celery's defaults mean a SIGKILLed child **ACKs** the message: it is never redelivered. The code's own comment at `:33-43` reasons about the time limits at length and never mentions that the *recovery primitive for a lost task is the database stale sweep* (`worker/beat_tasks.py:183-200`, up to `interval + 2 × STALE_INFLIGHT` ≈ 24 h 20 min, Session A `AUDIT-4B-5`).
- **Root cause**: the comment states an outcome and attributes it to the nearest visible setting, without naming the mechanism that actually delivers it. Phase 4B found this false; I confirm it and note that it is the natural place a maintainer looks to answer "why is a lost scan recoverable?", so the wrong answer is load-bearing.
- **Proposed remedy category**: comment correction naming the real recovery primitive; optionally a `task_reject_on_worker_lost` decision.
- **Source**: Phase 4B's finding, re-confirmed in Phase 9 as the doc-drift item Session A routed here

### [NEW] AUDIT-9-15 — `/openapi.json` is public, unmetered, and narrates the SSRF gate
- **Severity**: **Medium**
- **Subsystem / file(s)**: `backend/app/main.py` (FastAPI app construction — `docs_url`/`redoc_url`/`openapi_url` left at their defaults), `backend/app/models.py` (`allow_private_networks` on `remediation_hooks`), `docker-compose.yml` (no auth in front of the app port)
- **Reproduction**: unauthenticated GETs against `http://localhost:8321`: `/openapi.json` → **200, 92 500 B**; `/docs` → 200, 1 007 B; `/redoc` → 200, 889 B; **`/docs/oauth2-redirect` → 200, 3 012 B** (Session A's figure confirmed exactly); `/api/openapi.json`, `/api/docs`, `/api/redoc` → 404. The schema contains `allow_private_networks` as a named parameter, the `sitemap` fetch, and SSRF-related description text.
- **Root cause**: the interactive docs were left enabled with no authentication and no rate limit, and the OpenAPI description text — written for developers — doubles as a machine-readable specification of the product's own security controls. `/docs/oauth2-redirect` being a fourth public route confirms the surface was never enumerated deliberately.
- **Reconciliation of Session A's two figures**: I measured **92 500 B** uncompressed, matching one of the two cited values exactly. I could **not** reproduce 99 585 B under any encoding; the likeliest explanation is a transfer-encoded `Content-Length` or an earlier commit. **Recommendation to the coordinator: carry 92 500 B as current, treat 99 585 B as superseded**, unless a sibling can identify its provenance — I am not going to guess.
- **Proposed remedy category**: exposure control on the documentation surface (auth-gate, disable in production, or meter it), plus a decision on whether the security-sensitive parameter descriptions belong in a public schema.
- **Source**: Session A's DOC-6, independently re-measured

### [NEW] AUDIT-9-16 — `lib.ps1` has a Windows argument-quoting bug that no current caller can reach
- **Severity**: **Low**
- **Subsystem / file(s)**: `scripts/lib.ps1:89-92` (`Quote-Arg`), `:104-109` (raw `.Arguments` string), `:117-146` (`Invoke-NativeWithDeadline`)
- **Reproduction**: `Quote-Arg` quotes any value matching `[\s"]` and escapes `"` → `\"`, but **does not double a trailing backslash**. Under `CommandLineToArgvW` rules, `"C:\some path\"` has its closing quote escaped by the backslash, so the argument swallows the rest of the command line. Traced all six call sites: `docker @("info")` (`install.ps1:95,105`; `update.ps1:51`; `uninstall.ps1:73`; `validate.ps1:54,64,189`) and `docker @("compose","version")` (`install.ps1:105`; `validate.ps1:64`) — **every argument vector is fixed, so no user-controlled path ever reaches `Quote-Arg`**. Varying paths (repo root, build-log dir, backup dir) are handled by `Join-Path` + `Push-Location`/`Set-Location`, or by `Start-Process -ArgumentList` (`lib.ps1:358`), which applies its own quoting.
- **Root cause**: a hand-rolled Windows quoting helper that covers spaces and quotes but not the backslash-before-closing-quote case, written for a use case (user paths as native args) that the current call sites happen not to exercise.
- **Severity: Low, and honestly scoped as latent** — zero current operator impact. Recorded so the remediation prompt does not discover it as a mystery when someone adds a path argument, and so a user path like `C:\Users\John Doe\…` (which this workspace does not contain) is not silently mishandled later.
- **Proposed remedy category**: correctness fix in a shared helper (one line), or delete the helper in favour of `Start-Process -ArgumentList`, which already does the right thing.
- **Source**: new (PROMPT-003 Phase 9, `OPS-6`)

### [NEW] AUDIT-9-17 — The beat schedule file lives in the container's writable layer and is undocumented
- **Severity**: **Low**
- **Subsystem / file(s)**: `docker-compose.yml:118-131` (beat has **no** volume), `backend/Dockerfile.worker:36` (`celery -A worker.celery_app beat --loglevel=info` → `PersistentScheduler` at `/app/celerybeat-schedule.db`, 12 288 B)
- **Reproduction**: `docker inspect wardress-beat-1 --format '{{json .Mounts}}'` → `[]`. The file is created in the container's writable layer and is lost on container recreate. **I confirm Session A's judgement that this is benign by construction** — all five periodic tasks are idempotent, which I independently re-verified at the script level (OPS-7) and which Session A verified at the task level — and that it is **undocumented**: zero mentions across `docs/*.mdx`, `README.md` and the Mintlify `SKILL.md`.
- **Root cause**: a default (`PersistentScheduler` writing next to the code) that nobody decided on and nobody wrote down. Benign precisely *because* every task is idempotent — a property a future maintainer could easily break without knowing this file existed.
- **Proposed remedy category**: documentation (one sentence in `docs/installation.mdx`), or an explicit named volume if the file is ever given state.
- **Source**: Session A `AUDIT-4B-8` residual, re-confirmed and routed to its documentation home

### Severity distribution (Rule 16 — one severity each)

| Severity | Count | IDs |
|---|---|---|
| **Critical** | **0** | — |
| **High** | **5** | AUDIT-9-1, AUDIT-9-2, AUDIT-9-3, AUDIT-9-4, AUDIT-9-5 |
| **Medium** | **9** | AUDIT-9-6, AUDIT-9-7, AUDIT-9-8, AUDIT-9-9, AUDIT-9-11, AUDIT-9-12, AUDIT-9-13, AUDIT-9-14, AUDIT-9-15 |
| **Low** | **3** | AUDIT-9-10, AUDIT-9-16, AUDIT-9-17 |
| **Total** | **17** | |

**No finding was escalated above High and none was deflated.** The five Highs are all *operator- or operator-tooling*-facing, which is the honest shape of this phase: I found no false-clean and no exploitable boundary that the earlier phases had not already rated Critical. AUDIT-9-1 is the closest candidate and I kept it at High deliberately: it is a *false alarm*, not a false clean, and §6.4 reserves Critical for the latter.

---

## 8. Log-vs-reality discrepancies

| # | prior claim | prior value | my measured value | disposition |
|---|---|---|---|---|
| L1 | "fusion reload is a bottleneck" (Phase 9 brief candidate) | implied per-call reload | **0** `json.loads` across 6 000 `layer9_fusion()` calls; 0.0135 ms/call; one-time load 0.2985 ms | **PRIOR CLAIM INVALIDATED.** Fusion is cached per process and the `_model_lock` cannot contend across processes. **The remediation prompt should not spend effort here.** |
| L2 | O-SA-3: "resize once per layer-4 call" | implied material win | **+34.3 ms (9.5 %)** at 1280×3000; **−21.9 ms (−3.6 %)** at 1280×4000; n=5+5 interleaved; sd 50–116 ms | **INVALIDATED — the sign flips between two plausible screenshot heights.** Do not implement. `cProfile` shows SSIM + `scipy.uniform_filter1d` + PNG decode dominate, not the resizes. |
| L3 | "layer 8 is a large share of detection cost" (brief) / Session A's **66 %** of ~1.44 s | 66 % | **93–95 %** of a 14 KB page; the share *falls* as pages grow because layers 2/3/5 grow linearly (L2: 1.12 → **138.90 ms** from 0.3 KB → 171 KB) while L8 saturates at 2.4–3.0 s | **BOTH CORRECT AT THEIR OWN SCALE — reconciled, not contradicted.** The durable statement is: **L8 is bounded by design; L2/L3/L5 are not.** |
| L4 | "regex compilation cost" (brief candidate) | implied per-element recompilation | 17 module-level `re.compile` at import; only **3** inline `re.*` sites; the hot one costs **1.725 µs** from `re`'s cache | **INVALIDATED.** No recompilation anywhere; the 54 ms import cost is once per worker **process in the parent, before fork** — not per scan. |
| L5 | `scan_tasks.py:48` "near-zero fused risk (~0.03)" | 0.03 | **0.3000** (n=6, my fixture) / **0.1907–0.2213** (Session A) | **Claim is 10× too low on my fixture.** Honest band across both: **0.19–0.30**. |
| L6 | `fusion.py:40` and `:192` "material-change bar … (0.35)" | 0.35 | `app/scanning.py:58` → **0.40** | **Both comments wrong**, by 0.05. And the real safety ceiling is `_UNMEASURED_RISK_CEIL = 0.30`, so the *conclusion* holds more strongly than the arithmetic. |
| L7 | "`docs/layers/3-link-audit.mdx` collects stylesheets and fonts" | relation-aware `link_href` at 0.6 | `_collect_refs` **never reads `el.get("rel")`**; all 7 `<link rel=…>` variants score **identically** (L3 0.417 / risk 0.3429) | **The docs describe a collector that does not exist.** |
| L8 | "`ruff check .` fails with 9 errors" (Session A) | 9 | **9**, exit 1, all `E501` in `backend/tools/run_stress_catalog.py` | **EXACT REPRODUCTION.** Same count, same file, same rule. |
| L9 | `/docs/oauth2-redirect` = 3 012 B (Session A) | 3 012 | **3 012** | **EXACT CONFIRMATION.** |
| L10 | OpenAPI schema = 92 500 B **and** 99 585 B (Session A cites both) | two values | **92 500 B** uncompressed, live | **RECONCILED as far as possible:** 92 500 B is current. I could not reproduce 99 585 B under any encoding and am not guessing its provenance. **Recommend the coordinator carry 92 500 B and mark 99 585 B superseded.** |
| L11 | `worker/db.py::task_session` per-task engine cost | 87.98 ms fresh / 6.59 ms pooled, 13× (Session A) | **95.06 / 5.32 ms, 17.9×, 89.74 ms wasted** (n=5) | **CORROBORATED** (mildly worse). |
| L12 | 24 individual MiniLM encodes = 626.5 ms; batched = 373.6 ms; 1.68× / −253 ms (Session A) | 1.68× | **606.8 / 345.0 ms; 1.76× / −261.7 ms** (n=3) | **CORROBORATED.** |
| L13 | Layer 4 does 8 `resize()` + 8 `convert()` per call (Session A) | 8 + 8 | **8 resize** (identical across 5 runs) + **8 convert** (2 in `_load_rgb` + 2 `convert("L")` + 4 inside `imagehash.phash`/`dhash`) | **EXACT CONFIRMATION**, and I localised the 4 extra converts and 4 extra resizes to `imagehash`, which re-converts and re-resizes the **full-resolution** grayscale twice per side. |
| L14 | `validate.ps1` "<4 GB RAM" advice vs a 12-child pool needing 5.90–7.4 GB (the brief) | flagged as a suspect | **Confirmed and quantified**: `docker info` `MemTotal` = 7 976 714 240 → `7.4` GB → `7.4 -lt 4` = `False` → **silent pass**, while 12 warm children = **79 %** of that ceiling and the host has **15.34 GiB** that the check never mentions. Also **zero** checks for disk space or port 8321. | **CONFIRMED, and the brief's framing is slightly off in the check's favour**: the threshold is not merely too low, the check **does not fire at all** on this host. |
| L15 | "`update.ps1` merges `.env.example` into `.env`" (the brief's premise) | a merge exists | **No merge exists.** 5 `.env` references in `update.ps1`, none a write; the only `.env` write in `scripts/` is `install.ps1:236`, first-run only. And the live `.env` is already **14 keys behind** `.env.example` with one dead key of its own. | **PREMISE FALSIFIED — which strengthens the finding.** The brief asked me to find a gap in a merge; there is no merge. |
| L16 | "Telegram bot direct DB bypass vs the API diagram" (the brief, DOC-3) | a diagram claims a bypass | **No such claim exists** in `docs/**`, `README.md` or the Mintlify skill (case-insensitive grep for 6 patterns → 2 unrelated hits). The code routes through `app/agent/tools.py` → `app/services.py`, i.e. one service layer, confirming Session A. | **PREMISE NOT FOUND IN THE REPO.** If Session A read a diagram, it is not under version control and I could not audit it. Restate as "the claim is not in the repository". |
| L17 | "hop-by-hop DNS rebinding" as the SSRF defence (README + `security-and-dev.mdx`) | hop-by-hop ordering is the defence | `docs/remediation-hooks.mdx:65` describes a **different and stronger** property ("*resolves the host once and **pins the connection to the resolved address***"). The two pages describe different guarantees. | **INTERNAL DOC CONTRADICTION, not a code-vs-doc one.** I did **not** re-derive Session A's `AUDIT-3-3` measurements and did not touch `app/ssrf.py` (Rule 12). The open question — which property the *site-probe* path actually implements — is flagged, not answered. |

---

## 9. Opportunities / Innovation ideas (Rule 17)

**O-9A — a "poisoned anchor" detector at the baseline boundary.** AUDIT-9-1's remedy does not have to be a better wall regex. The cheapest correct gate is a **content-shape** check at the point where a baseline is promoted, entirely independent of `http_status` and of any vendor marker: a candidate baseline is refused (or promoted with a `suspect` flag requiring one confirmation re-fetch) when the document is *implausibly small relative to its own screenshot* (a 478-byte `page.html` next to a 1 280×1 400 PNG is a 3 000× ratio), when its visible text is below a floor, or when the ratio of visible text to DOM size is in the bottom percentile for the site. This catches paywalls, consent walls, captchas, and every vendor, today and tomorrow, and it costs three cheap arithmetic checks on data the capture already produced. **Why it beats a vendor list:** the failure mode is not "a marker we forgot" — it is "this document is not the page", which is vendor-independent and testable with a property-based corpus.

**O-9B — make `looks_like_challenge_page` extensible without making it a vendor list.** Today it is three Cloudflare predicates hardcoded in one function, which is why every other vendor passes. A registry of `{name, dom_probes: [...], title_prefixes: [...], status_header_pairs: [...]}` entries, each with a hermetic fixture pair, would let vendors be added without touching the hot function — and, more importantly, would make the *coverage* visible: a test that asserts "every vendor in the stress catalog has a registry entry" turns an unknown unknown into a tracked gap. This is the same shape as the existing `training/regression_corpus.json` and would reuse its discipline.

**O-9C — one `.env` reconciliation primitive shared by install, update, validate and diagnostics.** OPS-2, OPS-7 and OPS-8 all reduce to "several scripts each re-derive the same facts (port, DB name, required keys) and have drifted". A single `Get-WardressEnv`-style helper in `lib.ps1` that parses `.env` once, exposes `Get-RequiredKey`/`Get-KeyOrDefault`/`Get-MissingKeys -Against .env.example`, and is used by all four scripts would make the OPS-1 reconciliation a one-line call instead of a fourth implementation, and would make `validate.ps1` able to say "you are missing 14 documented keys" instead of nothing.

**O-9D — an operator-facing "expected vs actual scans in the last 24 h" surface, extended to the anchor.** Session A proposed O-SA3-B ("coverage gap") for scan frequency. The natural extension is the same number **per anchor**: "this site has produced N flagged scans in 24 h, every one of them from the same baseline captured at T". That single query would have made AUDIT-9-1 self-diagnosing — a permanently-`flagged` site with an unchanged, week-old anchor is a *shape*, not a log line — and it needs no change to any of the mechanisms in this report.

**O-9E — make the layer-cost curve a test, not a comment.** §1.3 established that L8 saturates at 2.4–3.0 s while L2/L3/L5 grow at ≈0.8 ms/KB without bound. A single hermetic test that runs `run_detection` at 30 KB and 300 KB and asserts (a) L8's cost is within a small factor across the two, and (b) L2's cost is *super-proportional* beyond a stated ratio, would (i) turn "layer 2 is the thing that will bite at scale" from a comment in an audit report into a checked property, and (ii) make any future optimisation of the normaliser or the DOM parser immediately visible. The O-1 invalidation is the proof of concept: a two-point A/B in one process is all it took to kill a plausible optimisation.

**O-9F — ship the diagnostics scrubber as a tested module, not a PowerShell literal.** OPS-4's 9/16 escape rate and its rule-ordering bug are both invisible because the scrubber is a hardcoded array literal in a `.ps1` with no test harness. Extracting the rule table into a data file plus a small test that runs a hostile corpus (a `wk_` key, a JWT, a Fernet key, a bot token, an Apprise URL, a base64 blob) and asserts zero escapes would have caught this at authoring time and would make the rule set reviewable in a diff. It is also the natural place to encode the *composition* case (a `DATABASE_URL` containing a `POSTGRES_PASSWORD`) that the ordering bug exposes.

---

## 10. New hermetic tests added

**None committed. Zero test files added to the repository.**

**Rule 5 / Rule 10 compliance and reasoning:**

- Every probe in this phase is a **diagnostic instrument**, not a regression test. Each one either (a) measures a number whose value is environment-specific (CPU-bound timings, contention-affected, host-specific RAM), or (b) requires a live Docker stack and a MiniLM model download. Committing any of them would put a machine-dependent assertion into the suite — precisely the "red suite" the rules forbid and the flakiness the existing harness works hard to avoid.
- The three findings that *would* make good committed tests — the layer-3 `rel` blindness (AUDIT-9-6), the `fusion.py:40`/`:192` 0.35-vs-0.40 drift (AUDIT-9-7), and the `celery_app.py:29-30` acks-late comment (AUDIT-9-14) — each **assert a gap**, so under **Rule 5** they must be `xfail`/skipped-with-reason if committed at all, and Rule 1 forbids me from making the production change that would turn them green. **They belong in the remediation prompt's test file, written after the fix**, not in the audit.
- I therefore kept all 9 probes in scratch, outside the repository, per **Rule 10**.

**Scratch probes written** (all under `C:\Users\Ns8pc\AppData\Local\Temp\opencode\w1c\`, none committed, none in the repo):

| file | what it proves |
|---|---|
| `prof_detect.py` | regex compilation cost (P9–P11); fusion caching via a `json.loads` counter (P6–P8); MiniLM cold load, warm floor, batched-vs-individual (P1–P5); `run_detection` per-layer attribution + cProfile (P13–P15); per-task DB engine A/B (P22–P24) |
| `prof_detect2.py` | layer 4 with **real** PNG screenshots — 8 `resize` + 8 `convert` counters, cProfile (P16–P19); document-size scaling of `run_detection` (§1.3) |
| `prof_detect3.py` | threshold-claim cross-check; `http_status` reader census; `list_sites` N+1 shape |
| `prof_detect4.py` | benign-churn band with screenshots (P27); 11-document ReDoS scope (P30); the 200-OK soft-block detection proof (risk 0.9714 vs control 0.30); layer-4 resize A/B (P20/P21, first pass) |
| `prof_layer4.py` | the instrumented layer-4 A/B that **reconciled** the resize accounting and produced the O-1 invalidation (P20/P21, decision-grade) |
| `probe_softblock2.py` | **the definitive `NB-CAP-2` end-to-end proof** — real `capture_baseline` + `run_scan` task bodies, scratch DB, `POISONED=True` / `risk=0.9999999999997338 flagged` / `interval=15` vs `CONTROL risk=0.3 changed interval=22`, plus the HTTP-403 positive control |
| `probe_layer3.py` | DOC-1: 9 `<link rel=…>` cases through the real layer 3 (0.417 for all seven); `rel`-blindness source proof |
| `probe_db.py` | `EXPLAIN (ANALYZE, BUFFERS)` over 10 hot query shapes (P25) — **the seeded pass FAILED on a schema mismatch (`sites.updated_at` does not exist) and both passes are therefore empty-table plans; reported as untested, not as index evidence** |
| `scripts/scrub_probe.ps1` + `scripts/fixrepo/.env` | OPS-4: the 16-probe hostile corpus against `diagnostics.ps1`'s verbatim scrubbing functions, pointed at a **synthetic** `.env` (9 escapes) |
| `p9*_results.txt` | captured stdout of each probe |

---

## 11. Full regression results

| command | result |
|---|---|
| `uv run --frozen ruff check .` (from `backend/`) | **`Found 9 errors`, exit 1** — all `E501 Line too long` in `backend/tools/run_stress_catalog.py:209,240,249,…`. **This is `ci.yml:58`, the first command of the backend job**, so `ruff format --check`, `pip-audit`, `check_torch_osv.py` and `pytest` never execute (AUDIT-9-9). Reproduced Session A's 9 exactly. **Not my regression** — `run_stress_catalog.py` was added outside this phase |
| `uv run --frozen alembic upgrade head` (against `wardress_w1c_test`) | 16 revisions applied cleanly, **24 tables** created — a fresh scratch DB for the `NB-CAP-2` probe |
| `docker exec wardress-test-pg psql … DROP DATABASE wardress_w1c_test WITH (FORCE)` | **DROP DATABASE** — scratch DB removed |
| `docker exec wardress-db-1 psql … SELECT counts` (live, post-session) | `sites=0 scans=0 baselines=0 alerts=0 users=1 apikeys=0 channels=0 suppression=0 hooks=0` — **live DB untouched; I created and removed nothing in it** |
| `Test-Path C:\data` (post-session) | **`False`** — the one place my artifact redirect initially failed (the default `/data/artifacts` resolves to `C:\data\artifacts` on this host) was found, cleaned, and the redirect fixed by overriding `worker.artifacts.artifacts_root` |
| `git status --short` (post-session) | `M Prompts/Pending/Finders/PROMPT-003/PROMPT-003-IMPLEMENTATION-LOG.md` (the coordinator's), plus Session A's and W1-A's scratch/test files. **Zero modifications to any tracked production file. Zero files of mine anywhere in the repo.** No temporary instrumentation left. |
| `docker compose ps` (post-session) | `wardress-app-1` Up 45 min **(healthy)** · `wardress-beat-1` Up 45 min · `wardress-db-1` Up 45 min **(healthy)** · `wardress-redis-1` Up 45 min **(healthy)** · `wardress-worker-1` Up 45 min. **Stack left running and unperturbed.** |
| `pnpm run type-check` / `pnpm test` / full `pytest` | **NOT RUN** — deliberate. The `ruff` failure above means the CI backend job's test step cannot run today (AUDIT-9-9), and running the full suite (~31 min, per Session A) under two contending siblings would have produced contention-poisoned timings and added load to a host with 4.46 GB free. I added no tests and changed no code, so there is nothing for me to regress. Session A's baseline of **1 457 passed / 10 deselected** remains the reference |

---

## 12. Findings routed OUT of phase scope (noted, not investigated)

1. **The site-probe path's actual DNS-binding property** — `AUDIT-9-12`/DOC-4 establishes that the *documentation* contradicts itself (hop-by-hop vs address-pinning), but which property the **site-probe** path implements is a question about `app/ssrf.py` and `worker/ssrf_transport.py`. **Rule 12: `app/ssrf.py` is never edited, and any SSRF finding is automatically Critical.** Routed to whoever owns the SSRF surface; I read no SSRF code beyond confirming that it is not what `ratelimit.py` does.
2. **The layer-3 `rel` filter (O-5)** is a **detection-behaviour** change, not a performance change. Routed to **Phase 8 / W1-B** (detection accuracy) and flagged in §6.2 so the coordinator can sequence it after the false-positive baseline is established.
3. **The O-2 batched-MiniLM change (261.7 ms/scan)** must be validated for output equivalence against the Phase 2 taxonomy corpus before it ships, which is detection work. Routed to Phase 8 for validation; the optimisation itself is performance.
4. **Frontend bundle work** — Session A's O-SA-6 (route-level `lazy()`: 1 077 kB / 404 kB gzip → 268 kB / 83 kB gzip). I did not re-measure it and it belongs to the frontend/Phase 10 surface.
5. **Capture-side optimisation** — Session A's O-SA-4 (event-driven banner wait, **−3.09–3.14 s** from every capture of a banner-free page ≈ 28 % of a 10.4–11.1 s capture) and O-SA-5 (parallel `probe_site` UA fetches). Both are `worker/fetcher.py` / `worker/probe.py`, which are **W1-A's and W1-B's** live-testing territory; measuring them would have contended with the siblings and risked perturbing the stack they depend on.
6. **`i3j4k5l6m7n8`'s upgrade deletes duplicate sites with cascade and no operator-facing warning** — Session A routed this to "Phase 9's docs/ops drift sweep" for the *operator-communication* half. **I checked and it is not communicated anywhere**: it appears only in the migration's own docstring, with no mention in `README.md`, `docs/**`, `scripts/install.ps1`'s output, or `update.ps1`'s. Recorded here; the remedy is a docs + script-output change and belongs with the documentation remediation.
7. **The `agent_messages` / `agent_conversations` retention gap** — Session A noted it and correctly ruled the agent subsystem out of blast radius per §0. I did not investigate.
8. **Ollama profile health** — `ollama` has no healthcheck and no observable readiness, so `docker compose --profile ollama up -d` reports "started" for a container that may still be pulling a model. Recorded as Low defect D4; a readiness probe belongs with the AI-provider work, not with topology.
