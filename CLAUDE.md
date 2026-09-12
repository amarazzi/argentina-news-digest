# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`brief.ar` (repo: argentina-news-digest). Daily digest of Argentine news for the previous
calendar day (00:00–23:59 Argentina time), sent via Telegram. Status: v0. Pipeline:

```
Recolector (RSS + Google News) -> Curador (dedup + ranking) -> Redactor -> Telegram
```

Full module-by-module explanation (in Spanish) is in [docs/como-funciona.md](docs/como-funciona.md)
and the README table — read those for the narrative version; this file is the operational + "gotchas"
layer on top.

## Commands

Setup:
```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
cp .env.example .env   # fill TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to send; GEMINI_API_KEY optional
                        # (without it, compose() falls back to a deterministic headline+link format)
```

Tests — **use `python -m pytest`, not the bare `pytest` console script.** `tests/test_group.py`
does `from tests.casos import cargar`; the `pytest` entry-point script doesn't put the repo root on
`sys.path`, so it fails collection with `ModuleNotFoundError: No module named 'tests'`. `python -m pytest`
adds cwd to `sys.path` and works. `tests/casos.py` has no `test_` prefix — it's shared fixture data, not
collected directly.
```bash
python -m pytest                              # full suite
python -m pytest tests/test_curate.py -k foo  # single test
ruff check .
python tools/e2e.py     # real feeds + a fake local Telegram server: validates HTML/length limits,
                         # forces 400/500 responses to check the retry + plain-text-fallback paths
```

Run:
```bash
newsbot --dry-run -v                        # console + writes previews/<día>.html (see below), no network side effects
newsbot --hours 12 --dry-run
newsbot --date 2026-09-08 --dry-run
newsbot --replay runs/2026-09-10.json.gz --dry-run   # re-curate a recorded day with today's code, no network
python tools/compare.py                     # diffs current curator's picks against every runs/*.json.gz day —
                                             # run this before merging any curate.py threshold change
set -a && source .env && set +a && newsbot --save-memory   # the real send; --save-memory is what
                                                              # actually writes to state/history.json
```

## Architecture

Orchestration is `cli.py`: `build_digest()` → `collect()` → `vectors_for()` → `curate_run()` →
`rank()`/`select()` (or `judge.select()`) → `write.compose()` → `telegram.send_message()`. Everything
below is what each stage assumes about its neighbors.

**Event identity has no stable UUID.** `identity.event_id()` = sha1 of the sorted, normalized set of
article titles in the event. It's a pure function of content, order-independent — but if an event's
article set changes at all between scoring, judging, and remembering, its id changes too. This is the
join key `record.py`, `memory.py`, and `judge.py` all use to refer to "the same event."

**curate.py (the biggest module) is a multi-stage heuristic pipeline, no ML beyond optional
embeddings:**
1. `cluster()` groups articles into `Event`s — semantic (via `group.py`'s agglomerative clustering on
   embedding cosine similarity, threshold 0.84) for articles that have vectors, Jaccard word-overlap
   (`cluster_by_words`, threshold 0.42, gated by `shares_discriminants` so filler words like "gobierno
   anunció" can't merge two unrelated stories) for the rest. **With fewer than 2 embedded articles it
   skips embeddings entirely** — no partial credit.
2. `merge()` runs a second, fixed-point pass fusing *events* (not articles) that are the same story told
   with different vocabulary, via containment overlap (not Jaccard) on each event's `topic()`.
3. `drop_junk`/`drop_previews` strip individual articles (not whole events) matching noise/routine/
   service/preview-announcement classifiers, each with a "hard news" escape hatch so e.g. a real surge
   in a routine weather report still gets through.
4. `score()` rewards independent outlets > raw copies > variants, and applies a 0.25 penalty
   (`NOISE_FACTOR`) if the *majority of all the event's articles* (not just the lead) look like noise —
   deliberately lead-independent, since which article becomes lead is a timing accident.
5. `select()` enforces absolute floors (`MIN_COVERAGE=3` outlets, `MIN_TAKES=2` independent takes) *and*
   a relative floor (1/3 of the top event's score) — a weak news day yields fewer stories rather than
   backfilling with filler. `WORLD_SLOTS` is a ceiling, currently 0: international coverage is collected
   and scored (for a repercussion bonus when it corroborates an Argentine story) but never gets its own
   slot in the digest.

**embed.py** calls Gemini's batch embedding endpoint, caches by content hash (so identical text across
days is never re-embedded), and caps input at 500 articles/day prioritized by outlet-overlap reach
(Gemini free tier is ~1000 embeddings/day). Any failure — missing key, API error, partial batch —
degrades silently to the word-based clustering path in curate.py; it never blocks the digest.

**memory.py** (cross-day dedup, `state/history.json`, 7-day retention) doesn't just match "have we
covered this topic" (Jaccard on `topic()` stems) — `is_repeat()` also checks whether today's event
introduces a fact-verb (murió, detuvieron, aprobó, …) not present in any matching prior entry. A
developing story ("internaron a X" → "murió X") shares almost no vocabulary day-to-day but *does*
introduce a new fact-verb, so it's let through instead of suppressed. `refresh()` replaces a repeated
topic's vocabulary with today's (not a union), so a story doesn't accumulate stems over a week until it
starts colliding with unrelated news.

**judge.py** (optional; off by default — `NEWSBOT_JUDGE=1` or `--judge`) is architected so the LLM only
*classifies* (category/scope/importance 1–10/relation-to-history) and plain code decides admission
(`admits()`, thresholds in env vars) — kept separate so exclusions stay explainable and tunable without
touching the prompt. It's gated off until its judgment has been compared against the deterministic
curator over a week of recorded `runs/` days (`--judge --dry-run -v` prints the score table; there's no
automated compare tool for this yet, unlike `tools/compare.py` which only diffs curator-vs-curator across
code changes). On `JudgeError`/`LLMError` (bad JSON, missing ids, retried once) the run falls back to the
deterministic curator and is recorded as judge-less.

**write.py** composes the Telegram HTML message: with a `GEMINI_API_KEY`/`OPENAI_API_KEY` it prompts an
LLM per the rules in `PROMPT` (never invent data not in the collected headlines/summaries; one link per
block; count the main fact, not the announcement-of-a-fact); without a key, or if the model's output is
unusable, it falls back to `fallback_message()` (headline + source's own summary + link, no generated
text). `verify.py` then checks each block for numbers/proper nouns not present in that event's own source
articles; an unsupported block is redrafted once, and if it's still unsupported it's replaced with the
plain deterministic block for that event — never published as-is.

**telegram.py** splits on Telegram's 4096-*visible*-char limit (tags don't count), never inside a tag
(keeps a stack of open tags across chunk boundaries). A 400 (malformed HTML) retries the same chunk with
tags stripped rather than failing outright; 429/5xx get linear-backoff retries.

**llm.py** is a thin HTTP wrapper (no SDK) with a model fallback chain — Gemini falls through to
lighter models on repeated 429 (daily quota, won't clear on retry), OpenAI has no fallback. Filters out
Gemini "thought" parts so a reasoning model that used its whole budget thinking (empty final answer)
raises `LLMError` instead of silently returning nothing.

**text.py** (`normalize`/`stems`/`keywords`/`discriminants`) is the single shared vocabulary layer
underneath curate.py, memory.py, and judge.py — `GENERIC_STEMS` (milei, gobier, anunci, …) is what stops
boilerplate from counting as topical similarity everywhere at once, and the ES/EN/PT `SYNONYMS` map
(falklands↔malvinas, inflation↔inflacion, …) is what lets `scope=world` coverage of a story cluster
with the Argentine coverage of the same story.

**alert.py** posts operational warnings (weak day / collection failure) to the same Telegram chat, on a
path independent from the digest send; `notify()` swallows its own `TelegramError` — an alert must never
be the reason a run fails.

**logs.py** redacts the bot token from any log message and silences `httpx`'s own logger (which at INFO
prints the full request URL, including `/bot<token>/...`).

**preview.py** (local-only, no network): `--dry-run` writes the composed message into
`previews/<día>.html`, wrapped to look like a Telegram bubble, so the actual rendered formatting can be
checked in a browser without touching the real bot. `previews/` is gitignored.

**record.py**: every `--save-memory` run writes `runs/<día>.json.gz` — raw articles (with the noise/
routine/service/preview flags applied), the full ranking (top 30) with coverage/score, chosen event ids,
judge verdicts (or null), and cached embedding vectors. **It does not store the final composed message
text** — the LLM-written paragraphs are never persisted anywhere once sent, only the ranking data that
produced them. The workflow commits these to a separate `runs` branch (not `main`), fetched by
`--replay` and `tools/compare.py`.

`sources.yaml`: two source kinds — `feeds` (direct RSS, `{name, url, scope}`) and `searches` (Google
News, `{query, lang, country, scope}`). `scope: world` is collected and scored but (per `WORLD_SLOTS=0`
above) never gets its own digest slot. Per-outlet `site:` searches are deliberate, not combined ORs —
Google News caps results at 100/query, and a combined OR query gets dominated by whichever outlet
publishes most.

## Environment notes (this machine)

- Git author/committer identity isn't configured globally on this machine — a plain commit picks up an
  auto-generated local email instead of the account's real GitHub email. Don't run `git config --global`
  (out of scope to change); if committing here, check `git log -1 --format="%ae"` against prior commits
  first and use `git -c user.email=... commit` / `GIT_COMMITTER_EMAIL=...` for just that commit if it
  doesn't match.
- `.github/workflows/digest.yml`'s cron is set for 06:13 AR, but GitHub has been observed to actually
  fire it 3–5 hours late on this repo (low-frequency schedule, low-traffic repo) — don't treat a late
  morning as a broken workflow without checking `gh run list` first.
