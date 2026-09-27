# OrgOS — Production Durability Audit

**Scope:** whole backend pipeline — Graph/auth layer, the human-decision write cascades, and the AI/agent pipeline. Focus: retries, silent failures, idempotency/races, cascade atomicity, and blocking work that should be async.

**How to read severity:** **High** = data loss, duplicates, silent wrong results, or outages under normal load. **Med** = degradation/inconsistency under growth or edge input. **Low** = hardening / cleanup.

---

## 0. The one pattern behind most of this

Two habits repeat across the codebase and cause the majority of High findings:

1. **No retry/backoff.** Neither the Graph client nor the LLM client retries a transient `429` / `503` / timeout. One blip = a failed user action or a failed extraction.
2. **Failure is swallowed into "empty".** Exceptions are caught and turned into `""`, `[]`, `None`, or a best-effort log — so callers **cannot tell "nothing happened" from "it failed"**, and the request still reports success.

Fixing these two at the two chokepoints (`graph/client.py::_request` and `agents/llm_client.py`) removes or de-risks a large fraction of the list. **Start there.**

---

## 1. Recommended fix order (phased)

**Phase 1 — Stop silent failures & transient outages (highest leverage, low risk):**
- R1 LLM client: retry/backoff + typed `LLMUnavailable` (not `""`).
- R2 Graph client: retry/backoff on 429/503/502/504/timeout, honoring the `Retry-After` **header**.
- R3 Extraction: surface a `degraded`/error status instead of silent `total_extracted=0` when the LLM produced nothing.
- R4 Audit-log writes: durable fallback + surfaced warning (never a silent compliance gap).

**Phase 2 — Idempotency & cascade safety (prevents duplicates/orphans):**
- I1 Consolidate the two Zone 1 accept endpoints; add the already-decided guard to `zone1_decide`.
- I2 Extraction write idempotency (dedupe against existing queue rows).
- I3 Idempotency guards on Zone 2/3 decides, gap→lifecycle, gap→risk; fix racy sequential ID generation.

**Phase 3 — Async / blocking (durability under load):**
- A1 Move the direct extract endpoints to the background-job pattern (we already did it for lifecycle-approve).
- A2 Offload classifier O(n²) + PDF/docx parsing to threads; cap + bound classifier LLM fan-out.
- A3 `standards_map`: index + short-TTL cache instead of full recompute per request.

**Phase 4 — Auth/config & resource bounds:**
- C1 `environment` default → production; hard-fail `skip_auth` outside dev.
- C2 Locks on token + JWKS refresh; bounded caches; pagination ceiling; JWT clock-skew leeway.

---

## 2. Retry & silent-failure findings

| ID | Sev | Where | Scenario → outcome | Fix |
|----|-----|-------|--------------------|-----|
| R1 | **High** | `agents/llm_client.py:172,203,267,363-375` (all backends) + `embedder.py:109,167,200` | Every backend does `except Exception: return ""`. A single gateway `429`/`503`/timeout becomes a valid-looking empty answer. | Bounded retry+backoff on 429/5xx/timeout; raise typed `LLMUnavailable` instead of `""` so callers distinguish failure from empty. |
| R2 | **High** | `graph/client.py:413-463` (`_request`) | Only 401 is retried. A routine Graph `429`/`503`/timeout fails the user's CRUD outright. | Retry loop (≈3 tries, exp backoff+jitter) for 429/503/502/504 + `httpx.TransportError`/`TimeoutException`. |
| R2b | **High** | `graph/exceptions.py:107` | `Retry-After` read from JSON **body** (`body.get("retry-after")`) — Graph sends it as a **header**, so it's always the hard-coded 60. | Parse `response.headers.get("Retry-After")`. |
| R3 | **High** | `agents/extractor/ollama_client.py:262-284,312-316`; `service.py:731-761` | LLM down → `_parse_response("")` → `[]` → `total_extracted=0`, **HTTP 200** — identical to "document had no controls". No alert. | Propagate empty/failed LLM as a `degraded` status or error; fail loud when the model produced nothing at all. |
| R3b | **High** | `agents/extractor/ollama_client.py:265,312-316` | Response hits `max_tokens` → truncated JSON array → `json.loads` fails → **whole chunk dropped** (all N controls lost). | Cap items per prompt, or salvage partial arrays (close array, drop last partial) before failing. |
| R4 | **High** | `review_queue/router.py:359-362,986-989,1172-1175`; `control_register/router.py:211-228` | Audit-log `create_list_item` fails → swallowed `logger.error`; the control is created and queue marked Accepted with **no audit record**. | Durable fallback (write the audit note into the item's `CascadeResult`) + return a warning flag; never only-log. |
| S1 | Med | `graph/client.py:685-687,736-739` | `resolve_user` transient error → returns blank `{display_name:"",email:""}`; a blank owner name can be persisted, indistinguishable from a real blank. | Distinguish transient (re-raise/sentinel) from not-found; don't map errors to blank-success. |
| S2 | Med | `agents/extractor/service.py:609-610`; `classifier/service.py:587,615,680`; `procedures_service.py:89-93` | Per-item write errors caught+counted; under throttling you get 3/20 written and a 200. | Track failures, reflect in response, retry throttled writes. |
| S3 | Med | `agents/extractor/service.py:741-745` (M1) | Auto-`run_classifier` failure swallowed; Zone 2/3 harmonisation silently never runs, extraction still "succeeds". | Surface a `classifier_status` in the response. |
| S4 | Med | `gap_analysis/router.py:384-410` (M4) | Lifecycle create fails (swallowed) but gap still advanced to "In progress" with no `LinkedLifecycleId` — remediation task silently doesn't exist. | If lifecycle create was expected and failed, don't advance the gap; 502. |
| S5 | Low | `agents/llm_client.py:208-227` | Health check can't tell a real 500 from a legit empty completion (generate never raises). | Depends on R1 (typed failure) — then health can distinguish. |

## 3. Idempotency, races & cascade atomicity

| ID | Sev | Where | Scenario → outcome | Fix |
|----|-----|-------|--------------------|-----|
| I1 | **High** | `review_queue/router.py:707-769` (`zone1_decide`) | **No already-decided guard.** Double-click/retry Accept → duplicate Control + Evidence + Audit. Sibling `control_register.accept_control:344-348` *is* guarded. | Add the same guard; ideally consolidate the **two competing** Zone 1 endpoints (`/decide` vs `/accept-control`) into one. |
| I1b | **High** | `review_queue/router.py:767` | Cascade writes Control/Evidence/Audit, then the final queue update fails → item stays "Pending Review"; retry re-creates everything (see I1). | Mirror `accept_control:514-539`: on final-update failure, audit the inconsistency and 502 "do not retry". |
| I2 | **High** | `agents/extractor/service.py:504-607` (`_write_to_queue`) | Dedup is only *within* a run. Re-extract (revised doc, or client retry) → **every control duplicated** in the queue. | Dedup against existing queue rows by `(SourceDocumentCode, normalised statement)`, or delete-prior-for-doc first (like the procedural path). |
| I3 | Med | `review_queue/router.py:994-1057,1180-1229` | Zone 2/3 decides have no idempotency guard → duplicate lifecycle tasks; re-escalate → duplicate Strategic Risks; Zone 3 re-runs owner rewrites. | Add already-decided guards. |
| I4 | Med | `gap_analysis/router.py:485-500,317-410` | Risk created, then gap update fails → orphaned risk + gap still Open; retry → **second** risk (guard is read-then-create with a race gap). | Idempotency key / `LinkedRiskId` check before create; compensate on failure. |
| I5 | Med | `gap_analysis/router.py:110-129,92-107`; `strategic_risks/router.py:128-145` | ID from `count+1` over a full-list read → two concurrent creates get identical `GAP-…-NNN` / `RSK-YY-NNN`. | Server-side counter or unique component (uuid/timestamp); don't derive from a live count. |
| I6 | Med | `control_register/router.py:576-617` | Reject after Accept sets Rejected but does **not** withdraw the already-created Active control/evidence → orphaned Active control. | Guard decisions on already-decided items, or compensate on reject. |
| I7 | Med | `evidence_tracker/router.py:258-291,335-372` | `submit`/`verify` have no state-transition or ownership guard: any user can re-submit an Accepted item (flips it back), or "verify" evidence never submitted. | Enforce transitions (verify requires Submitted; no submit once Accepted) + owner check. |
| I8 | Med | `agents/extractor/service.py:652-691`; `procedures_service.py:60-96` | Procedural re-index **deletes** from Chroma + SharePoint *before* writing; mid-way crash loses that doc's steps and desyncs the two stores. | Write-then-swap (index new, delete old only on success) or reconcile on failure. |

## 4. Blocking / should-be-async

| ID | Sev | Where | Scenario → outcome | Fix |
|----|-----|-------|--------------------|-----|
| A1 | **High** | `agents/extractor/router.py:51,119` → `service.py:731-750` | Direct extract endpoints run the *whole* pipeline in one request: up to 12 sequential heavy chunks (120s each, or a **10-min** RunPod poll), then synchronous classifier, then procedural embeddings — tens of minutes; client/proxy timeout → retry → two pipelines. | Enqueue as a background job (APScheduler already present); return a job id + poll. (Lifecycle-approve already backgrounded ✅.) |
| A2 | **High** | `agents/classifier/service.py:389-413,444-451` | O(n²) all-pairs `SequenceMatcher`, pure CPU, no `await` — **freezes the event loop**; auto-runs after every extraction. Thousands of rows → minutes unresponsive. | `asyncio.to_thread` + pre-block candidates (length bucket / token overlap) before the quadratic compare. |
| A3 | **High** | `agents/classifier/service.py:552-616,651-681` | One awaited `_semantic_assist` LLM call **per finding**, uncapped; runs after every extraction → cost/latency runaway on a messy import. | Cap findings/run; bounded-concurrency batch (`Semaphore`); enrich only top-N by score. |
| A4 | **High** | `standards_map/router.py:157-233,240-318` | Rebuilds traffic lights from **full** register reads with nested `any()` over evidence×controls, per request, no cache. | Fetch once → build `LinkedControlId→evidence[]` + `clause→controls` indexes (O(n)); short-TTL cache. |
| A5 | Med | `agents/extractor/service.py:97-105,138-140`; `cdi_checker/service.py:184-210` | pypdf/mammoth parsing is sync inside `async` — a large/scanned PDF blocks all concurrent requests. | `await asyncio.to_thread(...)`. |
| A6 | Med | `control_register/router.py:99-146`; `evidence_tracker/router.py:122-198` | `GET /controls` / `/evidence` **mutate** SharePoint and do N+1 sequential writes (owner-status sync) inside a read. | Move reconciliation to the cascade or a background job; keep GET read-only. |
| A7 | Med | `review_queue/router.py:550-672,760-764` | Owner-variant harmonisation (full-list scan + serial writes) and a full `run_classifier` run **synchronously inside** the decide request. | Background-job the fan-out + classifier. |
| A8 | Med | `agents/llm_client.py:353-365` | RunPod sync path polls `for _ in range(120): sleep(5)` = up to 10 min per chunk. | Bound total poll time; cap concurrent long-polls. |
| A9 | Low | `agents/nl_search/vector_store.py:93-133,169-222` | Chroma upsert/query are sync HNSW calls from async fns; fine now, will block on large collections. | `to_thread` when collections grow. |

## 5. Auth, config & resource bounds

| ID | Sev | Where | Scenario → outcome | Fix |
|----|-----|-------|--------------------|-----|
| C1 | **High** | `config.py:81,85` + `auth/validator.py:178` | `environment` defaults to `"development"`; a prod deploy that forgets `ENVIRONMENT` + has `SKIP_AUTH=true` → every request silently `OrgOS.Admin`. | Default `environment="production"`; hard-fail startup if `skip_auth` set outside an explicitly-named dev env. |
| C2 | High | `graph/auth.py:45-97` | No lock around token cache; concurrent expiry → N simultaneous token POSTs (can get the token endpoint throttled); single transient token error → request fails (no retry). | `asyncio.Lock` (double-check inside) + small retry on transient token errors. |
| C3 | Med | `graph/client.py:513-527` | `get_list_items` has no total-item/page ceiling → a large or unfiltered list loads entirely into memory with unbounded sequential calls. | `max_items`/`max_pages` cap; raise or paginate when exceeded. |
| C4 | Med | `graph/client.py:650,691` | `_user_cache` / `_sp_user_id_cache` are unbounded module dicts (grow for process life; no negative caching). | Bounded TTL/LRU (`cachetools.TTLCache`). |
| C5 | Med | `auth/validator.py:56-74,104-109` | Empty JWKS `keys=[]` cached for full TTL; unlocked refresh can stampede. | Don't cache empty key sets; lock the refresh. |
| C6 | Med | `auth/validator.py:132-141` | `jwt.decode` with `leeway=0` → minor clock drift rejects valid tokens (intermittent 401s). | `leeway` ≈ 60–120s. |
| C7 | Med | `graph/client.py:44-53,375-401` | Shared httpx client never re-created if closed/failed → every request `RuntimeError` until full restart. | Lazily (re)init in `get_client()` under a lock. |
| C8 | Low | `graph/client.py:460-463` + callers `:523,577` | `_request` returns `None` on 204/empty; callers do `.get(...)` → `AttributeError` on an unexpected empty body. | Return `{}` for non-DELETE, or guard callers. |
| C9 | Low | `auth/validator.py:160` + `graph/client.py:666` | Token with no `oid`/`sub` → `oid=""` → resolved as "Dev User". | Reject tokens lacking `oid`/`sub`. |
| C10 | Low | `graph/client.py:378-380,1056` | Large drive download bound by the shared 30s read timeout → mid-download timeout on big files/slow links. | Longer per-request timeout for drive up/downloads. |

---

## 6. Patterns already done well (reuse these)

- `control_register.accept_control` — compensates evidence-step failure by **withdrawing** the control (`:449-471`), and handles the post-cascade queue-update failure loudly (`:514-539`). This is the template `zone1_decide` is missing (I1/I1b).
- `review_queue` cascades use `CascadeError` + `_mark_cascade_failed` to mark an item **Blocked** on failure so it doesn't look decided.
- `strategic_risks.update_risk` enforces a real `VALID_TRANSITIONS` matrix (`:40-47,325-335`) — the guard evidence/queue endpoints lack (I7).
- `cdi_checker`, `gap_analyzer`, and `classifier._semantic_assist` **fall back to deterministic output** on empty/malformed LLM responses — the extraction path (R3) is the notable exception.
- Lifecycle approve/skip now runs extraction in the background (`_background_extract_and_flag`) — the template for A1.

---

*Generated from a three-part parallel audit (foundational layer · write cascades · AI pipeline). Fix in phase order; Phase 1 items R1–R4 give the most durability per unit of change and are the safest to land first.*
