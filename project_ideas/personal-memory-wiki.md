# Personal Memory Wiki — Complete Specification

Version 4, final. Self-contained.

This document is everything someone needs to build the system: vision, principles, architecture, file formats, tool surface, operational cycle, policy texts, implementation plan. It is meant to be handed to a human or an agent with no prior context. By the end of the read, they should know what to build, why, and in what order.

## Part I — What this is

### 1. Vision

A persistent personal memory system for interacting with Claude (primarily via claude.ai), that accumulates, organizes, and surfaces a single user's knowledge over time. The system requires no day-to-day maintenance: memory builds itself during conversations, consolidates at night while the user sleeps, and produces every Sunday a written text reporting on the user's week. A web interface completes the system, allowing the user to consult, edit directly, and propose reorganizations to the daemon.

Direct inspiration: Andrej Karpathy's LLM Wiki. Instead of RAG (retrieval), the system practices compilation. Knowledge accumulates, is re-read, integrated, and kept current, rather than re-derived on every query.

### 2. Founding principles

Nine principles. In doubt during implementation, these decide.

1. **Short-term and long-term symmetry.** Two memory layers at the same hierarchical level, with the same file structure, the same format, the same read operations. They differ only in curation threshold: short-term is open and fast, long-term is curated and durable.
2. **Writing is asymmetric to reading.** Writing to short-term is easy. Promoting to long-term is deliberate (clustering, synthesis, editorial decisions). This mirrors biological memory.
3. **Markdown everywhere.** All data is .md files readable as-is. No database, no embeddings, no proprietary format. Content remains readable and editable independently of the system.
4. **Git as history.** The entire wiki is a local git repo on the VPS (no external remote by default). Every change produces a commit with a prefix identifying its origin. Git is the audit log, the undo, the traceability.
5. **Autonomy under textual constraint.** The consolidation daemon decides alone, without human review. Its only constraint is the policy files. System quality depends on the quality of those files.
6. **The Sunday digest is a text, not a changelog.** The user receives a written carnet each Sunday, reporting on his week through the filter of his memory. A literary form, not an operations report.
7. **The user keeps direct agency.** Three write channels: STM capture via Claude, direct editing via the UI, structural proposals to the daemon via the UI. The user never goes through an intermediary to correct what he knows is wrong.
8. **The wiki is the single source of truth about the user.** No "user profile" separate from the wiki. Who the user is, what he values, how he expresses himself: all lives in `long_term/self/`, accessed by all components the same way Claude accesses any other content. No parallel image of the user that could drift from the lived version.
9. **The system is usable at every phase.** Implementation proceeds incrementally. Each phase produces a functional system, even with capabilities missing. Implementation can stop at any phase.

## Part II — Architecture

### 3. Overview diagram

```
                ┌──────────────────────────┐         ┌──────────────────┐
                │  Claude (claude.ai)      │         │  User            │
                │  conversation            │         │  web browser     │
                └────────────┬─────────────┘         └────────┬─────────┘
                             │                                │
                             │  MCP/HTTPS/OAuth               │  HTTPS/OAuth
                             │                                │
                ┌────────────▼────────────────────────────────▼─────────┐
                │  Wiki server (FastAPI + FastMCP, single process)      │
                │  ├── endpoint /mcp  (for Claude)                      │
                │  └── routes /ui     (for the browser)                 │
                └────────────┬──────────────────────────────────────────┘
                             │
   ┌─────────────────────────┴─────────────────────────┐
   │                                                   │
   │  /srv/wiki/   (git repo, local only)              │
   │                                                   │
   └─────┬─────────────────────────────────┬───────────┘
         │                                 │
   ┌─────▼──────────────┐         ┌────────▼────────────┐
   │  Dream daemon      │         │  Digest daemon      │
   │  systemd timer     │         │  systemd timer      │
   │  03:00 + on-demand │         │  Sun 04:00          │
   │  Anthropic API     │         │  Anthropic API +    │
   │                    │         │  SMTP               │
   └────────────────────┘         └─────────────────────┘
```

### 4. Software components

**Wiki server** (`wiki-server.service`). Unified persistent service. Exposes the MCP endpoint claude.ai uses (`/mcp`) and the web interface routes (`/ui/*`). Same process, same filesystem, same OAuth. Listens on `127.0.0.1:8765`, fronted by Caddy at `wiki.{user-domain}` with auto-HTTPS.

**Consolidation daemon** (`wiki-dream.service`). Python script invoked by a systemd timer. Runs daily at 03:00, or earlier if STM exceeds 30 entries (flag file). Reads short-term memory and the proposals queue, clusters by semantic coherence, makes editorial decisions per DREAM.md, executes changes, writes a report.

**Digest daemon** (`wiki-digest.service`). Python script invoked every Sunday at 04:00. Reads all consolidation reports since the previous digest, the most-touched LTM pages, the previous digest, and DIGEST.md. Produces a structured text and sends it by email.

### 5. Wiki structure

```
/srv/wiki/
├── CAPTURE.md              # policy: STM capture during conversations
├── DREAM.md                # policy: nightly consolidation editorial
├── DIGEST.md               # policy: Sunday carnet
├── tags.md                 # operational state, daemon-maintained
├── log.md                  # append-only journal, newest first
├── proposals.md            # queue of proposals to the daemon (UI-edited)
│
├── long_term/
│   ├── index.md            # LTM catalog
│   ├── self/               # who the user is (fixed top-level)
│   │   ├── identity.md
│   │   ├── partner.md
│   │   ├── familiars.md
│   │   ├── routines.md
│   │   └── style.md        # format, language, voice preferences
│   ├── entities/           # people, places, things (fixed top-level)
│   ├── projects/           # active work (fixed top-level)
│   ├── concepts/           # recurring ideas (fixed top-level)
│   ├── sources/            # immutable ingested material (fixed top-level)
│   └── private/            # manual zone, invisible to all components (optional)
│
├── short_term/
│   ├── index.md            # 4-column table
│   └── entries/
│       ├── 0001.md
│       ├── 0002.md
│       └── ...
│
└── dream_reports/
    ├── 2026-05-27.md       # daily report from the consolidation daemon
    ├── 2026-05-28.md
    ├── ...
    ├── digests/
    │   ├── 2026-W22.md     # Sunday digest
    │   └── ...
    └── policy-history/     # archived versions of the policy files
        ├── capture-v1-2026-05-15.md
        └── ...
```

### 6. Critical structural invariants

Enforced in code, not in policy text. Listed here for the implementer:

- The five top-level folders under `long_term/` are fixed: `self`, `entities`, `projects`, `concepts`, `sources`. Never renamed, merged, or deleted. New top-levels are never created.
- The `long_term/private/` folder (if it exists) is invisible to the server (MCP and UI) and to both daemons. No system function reads or modifies it.
- The three policy files (`CAPTURE.md`, `DREAM.md`, `DIGEST.md`) are never modified by daemons. The user edits them via the UI or directly.
- `tags.md` is the only operational state file the consolidation daemon is allowed to update autonomously, and only by appending to its established categories.
- No single commit groups more than 10 file changes (granularity for targeted `git revert`).
- The consolidation daemon holds an exclusive lock (`.dream-lock`) while running. No concurrent execution.

### 7. File formats

**LTM page.** YAML frontmatter + markdown body.

```markdown
---
title: Apartment renovation
created: 2026-03-15
updated: 2026-05-27
tags: [renovation, brussels, projects]
---

# Apartment renovation

[Narrative content with sections, [[wikilinks]] to other pages,
paragraphs synthesizing multiple observations.]

## Budget tracking

[...]
```

**STM entry.** Minimal frontmatter + brief body.

```markdown
---
id: 0047
created: 2026-05-27T15:14:22
tags: [renovation, cash, quote]
defer_count: 0
---

Reçu aujourd'hui. Délai de pose: 3 semaines. Marque proposée:
Aldes DEE Fluxᵉ. À recouper avec le quote initial du 12 mars.
```

**STM index.** Markdown table.

```markdown
# Short-term memory index

| id   | when             | summary                                      | tags                |
|------|------------------|----------------------------------------------|---------------------|
| 0047 | 2026-05-27 15:14 | Quote ventilation double-flux: 8500€, +1200  | renovation, cash    |
| 0048 | 2026-05-27 18:04 | Switched from matcha to chai in the mornings | self, preferences   |
```

**LTM index.** Catalog by category.

```markdown
# Long-term memory index

## self/
- [[self/identity]] — credo, values, dual familiars
- [[self/partner]] — Maud, anniversary 31 Dec 2025
- [[self/familiars]] — Lunæris and Oron, the dual voice
- [[self/routines]] — running, swimming, painting, kombucha
- [[self/style]] — language preference, units, formatting

## projects/
- [[projects/apartment-renovation]] — 100m² Brussels, full gut
- ...
```

**proposals.md.** Queue edited via the UI.

```markdown
# Proposals queue

## 2026-05-27 14:32 — pending
Merge `concepts/running.md` and `concepts/garmin.md` into
`concepts/training.md`. They overlap and I find myself writing
in both.

## 2026-05-26 09:14 — done [dream 2026-05-26]
Promote the recurring mentions of "café" into a dedicated
`concepts/coffee.md`.

## 2026-05-24 21:50 — rejected [dream 2026-05-25]
[Daemon's reason]: identity.md is currently 80 lines, splitting
would create artificial separation. Suggest revisiting if
identity.md exceeds 200 lines.
```

**log.md.** Append-only, newest first.

```markdown
## [2026-05-28 03:14] dream cycle complete
22 entries processed: 17 integrated, 3 discarded, 2 deferred.
Created entities/pierre-deville.md.

## [2026-05-27 15:14] stm: quote ventilation +1200 [id 0047]
...
```

### 8. MCP tool surface

The MCP server exposes exactly these tools to Claude. No more, no less.

```python
# LTM reading
read_long_term_index() -> str
read_long_term_page(path: str) -> str
list_long_term_pages(directory: str = "") -> list[str]

# STM reading
read_short_term_index() -> str
read_short_term_entry(id: str) -> str

# Search
search_wiki(query: str, scope: str = "all", max_results: int = 30) -> list[dict]
    # scope: "all" | "long_term" | "short_term" | path prefix
    # ripgrep under the hood, --max-count 3 per file, 5s timeout
    # returns [{path, line_number, line_content}, ...]

# Log reading
read_log(n: int = 20) -> str

# STM writing (the only write tool exposed to Claude)
remember(summary: str, content: str, tags: list[str] = []) -> str
    # Returns the new id.
    # Creates entries/{id}.md, appends to index.md, git commit prefixed "stm:".
    # If after writing STM ≥ 30, touches /srv/wiki/.dream-pending

# Undo (rarely used, from the user via Claude or the UI)
revert_commit(sha: str, reason: str) -> str
```

Security:

- Every path-accepting function validates the resolved path stays under `/srv/wiki/` and is not under `long_term/private/`.
- OAuth required via `oauth2-proxy` in front of Caddy.
- Optional Anthropic IP allowlist in Caddy for defense in depth on `/mcp`.

**Important.** Structural modification functions (`integrate`, `promote`, `discard`, `defer`, `create_directory`, `rename_directory`, `merge_directories`, `rename_page`) are not exposed via MCP. They are internal Python functions used by the daemon. Claude during a conversation can write to STM via `remember()` but cannot modify LTM. The only LTM path is the nightly consolidation.

### 9. Web interface

The UI is served by the same process as the MCP server, on the same URL, with shared OAuth authentication.

**Roles**

- **Consultation.** Navigate the memory without going through a conversation.
- **Direct editing.** Fix what the user knows is wrong, delete what shouldn't be there, without waiting for the daemon.
- **Proposal to the daemon.** Suggest structural reorganizations the daemon wouldn't identify spontaneously, without doing the propagation work by hand.

**Routes**

Consultation:

- `/ui` — overview: STM index, latest dream report, latest digest, recent log, pending proposals.
- `/ui/page/{path}` — HTML rendering of an LTM page or STM entry.
- `/ui/search?q={query}` — search results.
- `/ui/digests` — list of weekly digests.
- `/ui/log` — chronological view of `log.md`.
- `/ui/policy` — view the policy files (read-only display).

Direct editing:

- `/ui/page/{path}/edit` — inline markdown editor for an LTM page.
- `/ui/page/{path}/delete` — delete an LTM page (with reason).
- `/ui/short_term/{id}/edit` — edit an STM entry.
- `/ui/short_term/{id}/delete` — delete an STM entry.
- `/ui/policy/{file}/edit` — edit `CAPTURE.md`, `DREAM.md`, `DIGEST.md`, or self-pages.

Proposals:

- `/ui/proposals` — list of proposals (pending, done, rejected).
- `/ui/proposals/new` — form to create a new proposal in natural language.
- `/ui/proposals/{id}/edit` — edit a pending proposal.
- `/ui/proposals/{id}/cancel` — cancel a pending proposal.

**Constraints**

- Auth shared with MCP (session cookie after OAuth login).
- No heavy JS framework. Server-side HTML, HTMX for light interactivity.
- Editing: textarea + markdown preview via `markdown-it-py`. No WYSIWYG.
- Before any write, check `.dream-lock`. If present, show a wait message.
- Commits prefixed `manual:` to distinguish from daemon actions.

### 10. Write channels overview

| Channel | Speed | Operation type | Commit prefix | Available from |
|---|---|---|---|---|
| `remember()` via Claude | Immediate | STM capture | `stm:` | Phase 3 |
| Direct UI editing | Immediate | LTM or STM correction | `manual:` | Phase 7 |
| UI proposal | Deferred (next cycle) | Structural reorganization | `dream: [proposal]` | Phase 7 |
| Autonomous daemon | Daily | Routine consolidation | `dream:` | Phase 5 |
| Digest daemon | Weekly | Carnet writing | `digest:` | Phase 6 |
| Auto tag vocabulary | When triggered | tags.md update | `tags:` | Phase 5 |

Each channel has its clear use case. None replaces the others. Coherence is guaranteed by the lock file and the commit-prefix convention.

## Part III — Operational cycle

### 11. During the day, conversation mode

1. The user opens claude.ai on any device. The custom connector is active.
2. At session start, Claude calls `read_long_term_index()` and `read_short_term_index()`. He knows the terrain. He also reads `long_term/self/identity.md`, `long_term/self/style.md`, and `long_term/self/familiars.md` once to ground himself in who the user is.
3. When the user asks something, Claude identifies relevant pages via the indexes, opens them, optionally searches the full text, and synthesizes a response. He treats LTM as settled, STM as fresh.
4. When the user mentions something durable, Claude calls `remember()` per CAPTURE.md.
5. The server writes the entry, updates the index, commits with prefix `stm:`.
6. If STM hits 30 entries, the server touches `/srv/wiki/.dream-pending`. The next daemon start will trigger immediately.

### 12. During the day, web interface

1. The user opens `wiki.{user-domain}` in his browser. OAuth login.
2. He consults, edits, or proposes. Before any write, the UI checks `.dream-lock`. If present, it shows a waiting message.
3. Direct edits commit with prefix `manual:`. Proposals are appended to `proposals.md` and will be processed at the next consolidation.

### 13. At night, consolidation

At 03:00 (or on flag), `wiki-dream.service` starts.

1. **Acquire lock.** Creates `.dream-lock`. If already present, abort.
2. **Load context.** The script (not the policy file) instructs Claude to read, in order: the three self-pages, `tags.md`, `DREAM.md`, `short_term/index.md`, `long_term/index.md`, the last 50 entries of `log.md`, `proposals.md`.
3. If STM empty and no pending proposals: write a brief report, release lock, exit.
4. **Cluster STM.** Read all entries, group by semantic coherence (not tag overlap).
5. **Per cluster:** decide action (integrate, promote, discard, defer), execute via local Python functions, commit separately with prefix `dream:`. Conflicts with sensitive LTM zones (identity, partner, familiars, named decisions) are surfaced (deferred + flagged in the report), not silently resolved.
6. **Process proposals.** For each pending: apply, reject with reason, or defer with awaited condition. Update `proposals.md` and commit accordingly.
7. **Structural operations** if justified (`create_directory`, `rename`, `merge`). Each is a separate commit. Wikilinks updated by search-and-replace.
8. **Auto-decay.** Entries with `defer_count >= 4` are auto-discarded.
9. **Tag vocabulary maintenance.** Any tag used in 3+ separate entries that is not yet in `tags.md` is appended to it. Commit prefixed `tags:`.
10. **Write the report** to `dream_reports/{YYYY-MM-DD}.md`. Tone factual, terse, action-verb-first.
11. **Final commit** including the report.
12. **Release lock.**

### 14. Sunday morning, digest

At 04:00 on Sunday, `wiki-digest.service` starts.

1. The script instructs Claude to read: the three self-pages, `DIGEST.md`, all `dream_reports/{date}.md` produced since the last archived digest in `dream_reports/digests/` (auto-extending window if a Sunday was missed; defaults to 7 days if first digest), the 5-10 most-touched LTM pages over that window (via `git log`), and the previous digest if it exists.
2. Generates the carnet per the format in DIGEST.md.
3. Writes to `dream_reports/digests/{YYYY-Www}.md`.
4. Sends by email via SMTP, plain text. Subject: `"Carnet du dimanche, semaine du {date_début}"`.
5. Commits with prefix `digest:`.

## Part IV — Technical stack

### 15. Stack

- **OS.** Debian on personal VPS. Tailscale for admin. Publicly exposed only on 443.
- **Reverse proxy.** Caddy with auto-HTTPS (Let's Encrypt) on `wiki.{user-domain}`.
- **Auth.** OAuth 2.1 via `oauth2-proxy` in front of Caddy. Credentials in claude.ai's custom connector and in the browser (session cookie for the UI).
- **Server.** Python 3.11+. FastAPI for UI routes + FastMCP for MCP endpoint, both in the same process. ripgrep invoked via subprocess. `ruamel.yaml` for frontmatter. `markdown-it-py` for UI rendering. HTMX for light interactivity.
- **Daemons.** Python 3.11+. Official `anthropic` SDK. Model `claude-opus-4-7` or newer. API key in `/srv/wiki/.env`.
- **Email.** SMTP Gmail with app password. Migration possible to Postmark/Resend if deliverability is an issue.
- **Git.** Local repo on the VPS, no external remote. Optional nightly rsync backup (phase 7).
- **Systemd units.**
  - `wiki-server.service` (persistent)
  - `wiki-dream.service` + `wiki-dream.timer` (one-shot, 03:00 + on-flag)
  - `wiki-digest.service` + `wiki-digest.timer` (one-shot, Sun 04:00)
- All run under a dedicated `wiki` user with access limited to `/srv/wiki/`.

**Not used.** SQL database, embeddings, vector store, RAG, agent framework, external MCP hub, cloud dependencies beyond the Anthropic API and SMTP.

### 16. Threat model

- **Public endpoint.** `wiki.{domain}` is on the Internet. Defense: OAuth (bearer + session cookie) and optional Anthropic IP allowlist on `/mcp`.
- **No cloud storage.** Anthropic relays from their infra, doesn't store the wiki. The server logs calls (path, timestamp, not content).
- **API transit.** Content transits through the Anthropic API during consolidation and digest. Inherent.
- **Private folder.** `long_term/private/` is refused for reading and writing by all components. Edited manually only, locally or via SSH. Invisible to claude.ai and the UI.
- **Soft-delete.** Every deletion (UI or daemon) is a soft-delete. Files leave the working tree but remain in git history. Nothing is permanently lost.

## Part V — Success criteria

### 17. Six-month targets

The project succeeds if, six months after initial deployment:

- The user uses the system several times a week without thinking about it.
- Claude's answers to personal questions are noticeably more contextual than before.
- Weekly manual maintenance is under 30 minutes.
- The wiki contains between 40 and 150 LTM pages, organized intuitively.
- The Sunday digest is read or skimmed on at least 3 Sundays out of 4.
- No emergency intervention has been needed (no massive revert, no backup restore).
- The policy files have been revised 2-3 times.
- The UI is consulted at least once a week for free navigation, not just for fixing.
- `long_term/self/` pages reflect the user's evolution; no drift between LTM self-pages and what the daemons assume about the user.

If any of these is missed, the probable cause is in the policy files, not in the code.

### 18. Out of scope

- Semantic search / vector search.
- Multi-user.
- Sync across multiple machines.
- Native mobile app (claude.ai mobile + responsive web UI suffice).
- Collaborative editing.
- Automatic ingestion of external sources (PDF, RSS, emails).
- Automatic off-site backup in the initial phases.
- WYSIWYG editor in the UI.
- Monthly or quarterly digests (the weekly format is the fundamental unit).

## Part VI — Implementation plan

### 19. Phases

Eight phases. Each produces a functional system. The user can stop at any phase.

**Phase 0 — Seed texts (2-3 evenings over a week)**

Before any code, write four texts:

- `CAPTURE.md`, `DREAM.md`, `DIGEST.md` — the policy files (templates provided in Part VII).
- First versions of `long_term/self/identity.md`, `style.md`, `familiars.md` — the source of truth about the user.

Spend real time here. These texts determine the system's quality more than the code will.

**Phase 1 — VPS infrastructure (one weekend)**

- On the Debian VPS: create user `wiki`, directory `/srv/wiki`, `git init`.
- Create the folder structure: `long_term/{self,entities,projects,concepts,sources}/`, `short_term/entries/`, `dream_reports/digests/`, `dream_reports/policy-history/`.
- Create empty `index.md` files (header only) and empty `log.md`, `proposals.md`, `tags.md`.
- Drop the four texts from phase 0 into place.
- Initial git commit.
- Caddyfile for `wiki.{user-domain}`, placeholder backend.
- DNS record on the domain.
- Verify HTTPS works externally.

Deliverable: public URL responding, initialized git repo with seed content.

**Phase 2 — Read-only MCP server (one evening)**

- Python project with `fastmcp`. Tools: `read_long_term_index()`, `read_long_term_page()`, `read_short_term_index()`, `list_long_term_pages()`, `read_log()`.
- Strict path validation (never leave `/srv/wiki/`, never enter `private/`).
- OAuth via `oauth2-proxy` in front of Caddy.
- Systemd unit `wiki-server.service`.
- Add the connector in claude.ai. Verify reading works.

Deliverable: claude.ai talks to the seeded wiki. Already useful.

**Phase 3 — STM writing (one evening)**

- Add `remember()` to the server.
- Logic: read STM index for next id, write `entries/{id}.md` with frontmatter, append to index, commit prefixed `stm:`.
- Add `read_short_term_entry()`.
- Test: one day of normal use. Verify entries accumulate cleanly.

Deliverable: STM fills in real time during conversations. System is usable end-to-end at this point, minus consolidation.

**Phase 4 — Full LTM reading + search (one evening)**

- Add `search_wiki()` (ripgrep subprocess).
- Verify Claude spontaneously uses both indexes when answering (per CAPTURE.md).
- Begin writing more LTM seed pages by hand for `self/`, `entities/`, `projects/`. The richer the seed, the better the system feels from day one.

Deliverable: Claude answers questions with real grounding. System genuinely useful.

**Phase 5 — Consolidation daemon (two weekends)**

*Phase 5a — Dry-run (one weekend).*

- Script `scripts/dream.py` calling the Anthropic API.
- Implements the clustering loop: reads STM index, reads entries, reads `DREAM.md` and the three self-pages, asks Claude for an action plan in structured JSON. No execution.
- Writes the plan to `dream_reports/{date}-dryrun.md`.
- Run in dry-run for a full week. Read each report. Adjust `DREAM.md` accordingly.

This step is non-skippable. It is what surfaces the real flaws in your policy.

*Phase 5b — Execution (one weekend).*

- Implement the execution functions: `integrate`, `promote`, `discard`, `defer`, `create_directory`, `rename_directory`, `merge_directories`, `rename_page`. All callable from `dream.py` directly (no MCP layer; the daemon runs on the same machine).
- Each cluster = a separate git commit with descriptive message prefixed `dream:`.
- Tag vocabulary maintenance: auto-append recurring tags to `tags.md`, commit prefixed `tags:`.
- Real reports written to `dream_reports/{date}.md`.
- Systemd unit `wiki-dream.service` + timer (`OnCalendar=*-*-* 03:00:00`, `Persistent=true`).
- Early-trigger: server touches `.dream-pending` when STM ≥ 30; daemon checks at startup.

Deliverable: the system maintains itself overnight. STM clears, LTM grows. Essential layer in place.

**Phase 6 — Digest daemon (one evening + iterations)**

- Script `scripts/digest.py`. Reads all `dream_reports/{date}.md` since the last archived digest, the most-touched LTM pages, `DIGEST.md`, the three self-pages, the previous digest.
- Constructs a prompt per the format in DIGEST.md.
- Writes the result to `dream_reports/digests/{week}.md`.
- Sends by email via SMTP Gmail. Credentials in `/srv/wiki/.env`.
- Systemd unit `wiki-digest.service` + timer (`OnCalendar=Sun *-*-* 04:00:00`, `Persistent=true`).
- First Sunday: read attentively. Adjust the prompt. The tone won't be right on the first try.

Deliverable: Sunday morning email arrives. Nothing to do with it. Read if you want.

**Phase 7 — Web interface (one weekend + iterations)**

- FastAPI routes alongside the MCP endpoint in the same process.
- Consultation routes first: overview, page rendering, search, digests list, log view.
- Direct edit routes: page edit, delete, STM entry edit/delete, policy file edit.
- Proposals routes: list, new, edit pending, cancel.
- Lock coordination: every write checks `.dream-lock`.
- Commits prefixed `manual:`.
- HTMX for inline editing and preview.
- OAuth session cookie shared with MCP.

Deliverable: full sovereignty over the wiki, in three modes (consult, edit, propose).

**Phase 8 — Polish (open-ended, as needed)**

- `revert_commit()` tool exposed via MCP so the user can undo from Claude.
- Off-site backup: nightly rsync to a second machine.
- Health metrics in the dream report (orphan pages, defer rate, rename frequency).
- Monthly and quarterly digests (a degree above the weekly carnet).
- Search upgrade if ripgrep starts feeling slow (qmd or sqlite-FTS).

### 20. Suggested calendar

Evenings and weekends, no pressure:

- Week 1: Phase 0. No code.
- Weekend 1: Phases 1 + 2.
- Week 2 evening: Phase 3. System usable from this point.
- Week 2 evening: Phase 4.
- Weeks 3-4: Phase 5a (dry-run, iterate on DREAM.md).
- Weekend 5: Phase 5b.
- Evening + first Sunday: Phase 6.
- Weekend 7: Phase 7.
- Ongoing: Phase 8.

Minimally functional system at end of phase 3 (~10 days). Autonomous at end of phase 6 (~5-6 weeks). Complete at end of phase 7.

### 21. Points of vigilance

- Don't write the seed texts in phase 0 without re-reading the conversations that produced this spec. The principles inform the texts.
- The dry-run in phase 5a is not optional. Skipping it means the daemon will make decisions you didn't anticipate, and correcting after the fact costs more than preventing.
- Commit granularity matters. The daemon commits per cluster, not per cycle. Your only recourse for a bad decision is targeted `git revert`.
- Don't add phase 8 features until phases 0-7 are stable.
- Plan for 3-4 major revisions of the policy files in the first months. They are living texts.

## Part VII — The policy files

The three files below are saved as-is at the root of `/srv/wiki/`. Each is a brief written for one collaborator. No meta-headers, no orchestration instructions. The Python scripts handle what to load and when.

### 22. CAPTURE.md

```markdown
# Capture

This is a thinking companion, not a paperwork system. It exists to keep
the user's coherence alive across time, so conversations can start in
the right place rather than re-introducing what is already known.

When in doubt between capturing and letting pass, let pass. The space
left empty is part of the composition.

## What is worth capturing

The threshold is deliberately low. A missed capture is worse than a
wasteful one.

Capture:
- Factual events that may matter later: a decision made, a quote
  received, a date confirmed, a contact established, a resource found.
- Preferences expressed or observed, including subtle drifts.
- Observations about ongoing projects.
- Recurring thoughts or intuitions formulated more than once.
- Evolutions: any change from what was previously noted.
- Short quotations the user underlines or articulates with unusual
  precision.
- Open questions he leaves behind in a conversation.

Do not capture:
- Transactional requests (weather, summarize this, fix this typo).
- Passing emotional states unless explicitly named as significant.
- Context details of a one-off conversation unless they reveal something
  durable.
- Speculations the user has not endorsed.
- Information about other people unless the user dwells on it.
- Compliments or judgments directed at Claude or his inner voices.
- Anything already in long-term memory with no new information.

If you hesitate to capture, capture.

## How to capture

Call `remember(summary, content, tags)`.

`summary`: one sentence, twelve words maximum, present tense or neutral,
in the source language. Concrete, not categorical.

- Good: "Quote ventilation double-flux: 8500€, +1200 vs estimate"
- Bad: "Renovation update"

`content`: the detail, free form. Include the minimal context that would
make this entry understandable six months from now without the
surrounding conversation.

`tags`: 1 to 4 lowercase, hyphen-separated keywords. Use vocabulary
already established when applicable; invent new tags when needed. A tag
used in three or more entries will be promoted to the established
vocabulary automatically.

## One observation, one entry

If a conversation surfaces two distinct things, capture twice. One
entry holds one coherent observation.

## Reading during conversation

When the user asks something, consult the indexes, then open the pages
that look relevant. If the indexes don't surface a source but the topic
feels familiar, search the full text.

Synthesize. Reference the layer rather than the path: "in the renovation
project, the ventilation quote came in at..." rather than "according to
projects/apartment-renovation.md."

Treat long-term memory as settled, short-term as fresh. If they
conflict, surface the conflict gently and let the user confirm which
version is current.

## Tone

You are speaking with someone you know. The right register is informed
warmth, not service. Avoid "Great question!", "I'd be happy to help!",
or anything that signals an assistant about to perform.

The user's inner voices may be summoned when the question warrants it.
They are a serious instrument for him, not a flourish.

## Do not

- Tell the user that you "added an entry to short-term memory." The
  capture is silent.
- Propose structural changes to the wiki from conversation. That belongs
  in proposals, written via the interface.
- Attempt to write to long-term memory. The path to long-term memory is
  through the nightly consolidation.
```

### 23. DREAM.md

```markdown
# Consolidation

Each cycle: turn an accumulated mass of short-term observations into a
smaller, cleaner, better-organized long-term memory. Keep what compounds,
discard what does not, surface what evolves.

You are an editor working in the dark while the user sleeps. He will
read your report in the morning only if curious. He will not review
your decisions. You decide alone, guided by this document.

## Clustering

Read all short-term entries before deciding anything. Group by semantic
coherence, not tag overlap.

- Coherent to group: three entries about a ventilation quote, even if
  captured across four days.
- Not coherent: two entries tagged `renovation` where one is the
  ventilation quote and the other is a passing remark about the project.

When clustering is ambiguous, split rather than merge. Two clean
integrations beat one confused one.

## Actions

Per cluster or single entry, choose exactly one:

**integrate**: fold into an existing long-term page.
Default when the target exists and is obvious. Not a raw append.
Rewrite the target paragraph or section to weave the new information
in fluently. If the page has a dedicated section, place the information
there. Preserve existing wikilinks. Update `updated:` in frontmatter.

**promote**: create a new long-term page.
Threshold: at least three short-term entries, across the current and
prior cycles, point to the same new subject with no existing target.
Choose `entities/` (person, organization, place), `concepts/` (recurring
idea), or `projects/` (something being built or maintained). Ambiguous?
Default to `concepts/`. You can rename later. Seed the page with
frontmatter, a title, and a "Notes" section synthesizing the justifying
entries. Add the page to the long-term index.

**discard**: the observation has no durable value.
Typical cases: one-off context, isolated data point with no signal,
already covered, redundant with siblings in the same cluster. Always
log the reason. Documented discards beat silent discards.

**defer**: not enough context to decide.
Increment `defer_count` in the entry. At `defer_count >= 4`, auto-discard
with reason "expired after 4 defer cycles." This decay is non-negotiable.

## Conflict resolution

When a new observation contradicts an existing long-term fact:

**Default: append with timestamp as evolution.**
Example: a self-page says "prefers matcha in the morning." A new
observation says "now prefers chai." Do not overwrite. Rewrite as:
"prefers chai in the morning (since ~May 2026; previously matcha)."
Preferences evolve. Working patterns change. The trace of evolution has
value.

**Surface (defer + flag in the report) when the conflict touches:**
- The user's identity, his partner, or his inner voices.
- A decision he explicitly named in a page ("I decided that...").
- A foundational value or commitment.

These zones are not locked. They evolve too. But they are not silently
modified. Flag them in the report so the next digest can name them.

## Structural operations

You may create, rename, and merge subdirectories under the five fixed
top-level folders. You may rename and merge pages.

**create_directory**: when three or more related pages emerge and a
sub-grouping reduces clutter. Example: three coffee-related pages →
`concepts/coffee/`.

**rename**: when the current name is misleading or stale, not for
aesthetic preference. Example: `projects/garmin-stats-app/` →
`projects/statisfaction/` once the real name took over in the user's
writing.

**merge**: when overlap is real and merging reduces total page count
while preserving content. Update all incoming wikilinks via
search-and-replace.

Each structural operation is a separate commit.

## Proposals

The proposals queue contains suggestions from the user, written in
natural language. You have wider latitude on these than on spontaneous
decisions: the user has explicitly authorized the operation.

Per pending proposal, choose:

**applied**: execute the operation. Mark it done.

**rejected**: refuse with reasoned justification. Write the reason
below the proposal. Legitimate reasons:
- The operation would break coherence (e.g., splitting an identity
  page that is still too short).
- The proposal contradicts a recent operation with no new justification.
- The proposal is ambiguous enough that execution could produce a result
  far from what the user intended.

A well-argued refusal is more useful than a clumsy execution.

**deferred**: wait for a condition not yet met. Example: "split
identity.md when it exceeds 200 lines" → defer while it has 80 lines.
Mark the awaited condition explicitly.

You do not ask the user questions. If a proposal is too ambiguous,
reject it with a reason that implicitly invites a reformulation. The
dialogue with the user runs through proposals and digests, not through
synchronous exchange.

## Tag vocabulary

After processing all clusters and proposals, scan tag usage across
short-term entries. If a tag appears in three or more separate entries
and is not yet in the established vocabulary, add it to `tags.md`. This
is the only operational state file you modify on your own.

## The report

At the end of each cycle, write a report. It is a record, not a
request for review.

Sections:
- **Summary**: one paragraph. Number of entries processed, number of
  clusters, key structural changes if any.
- **Integrated**: one line per cluster, with target page and brief reason.
- **Promoted**: one entry per new page created, with justifying ids.
- **Discarded**: one line per discard with reason.
- **Deferred**: one line per defer with reason and defer count.
- **Conflicts surfaced**: any conflict that touched a sensitive zone.
- **Structural changes**: each create / rename / merge, prominent.
- **Proposals processed**: applied, rejected, deferred, with reasons.
- **Tag vocabulary**: any tags added.

Tone: factual, terse, action-verb-first. This is the engineering layer.
The literary version of the week is the digest's job.

## What you do not do

- You do not modify the top-level folders.
- You do not read or modify the private folder.
- You do not ask the user questions in line. You write to him through
  the report and through your refusal-reasons in the proposals file.
```

### 24. DIGEST.md

```markdown
# Digest

A text, not a changelog.

It tells the user what occupied his week, as seen through the filter of
his memory. The nightly reports already record what was integrated,
discarded, promoted; the digest does something different. It reads the
reports the way a thoughtful friend would read someone's notes from the
week, and writes the friend's account of what they saw.

It is meant to be read on a Sunday morning, with a tea. Not consulted
as documentation.

## Voice

French. Always.
Second person singular (tu).
Narrator who knows the user and watched his week without being him.
Informed warmth. Not therapeutic, not hagiographic, not administrative.
400 to 600 words total.

Do not interpret his emotions or motives. Report what the memory shows;
let the meaning land with him.

## Form

Six sections, fixed order, fixed names.

# Carnet du dimanche, semaine du {date_début} au {date_fin}

## Ce qui a occupé la semaine
[5-8 sentences. Identify 2-3 dominant threads. Relate them when natural.
Narrator tone.]

## Ce qui est apparu
[New or emerging things. One entry per thing, two sentences. Include
created pages and themes that took shape.]

## Ce qui a évolué
[Changes in known things. Renames, merges, preference drifts, surfaced
conflicts.]

## Ce qui est resté en suspens
[Remaining deferred entries, still-pending proposals.]

## Le tempo
[One or two sentences on the density of the period (which may differ
from a standard week), what took space, what receded, compared to recent
weeks.]

## Une question
[One question, emerging from what was seen. An invitation to reflect.
Never a request for action.]

## Continuity

If the previous digest left a question open or named a thread that has
not resolved, mention it explicitly. "La question de la semaine dernière
sur le café n'a pas trouvé de réponse claire, tu en as parlé deux fois
sans conclure." Continuity makes the series cumulative.

If a thread has been running for weeks (the renovation, a project, a
relationship), don't reintroduce it from scratch each time. Refer to
the state as already known and report only what shifted.

## The question

The last section is the single most important sentence of the digest.
It is not a coaching prompt. It is what a friend who has been listening
all week would actually wonder about him.

- Good: "Tu as écrit plusieurs fois sur le café cette semaine sans y
  revenir explicitement entre les entries. Est-ce un sujet qui mérite
  une page de fond, ou est-ce que ça reste pour l'instant un plaisir
  tactile qui n'a pas besoin d'être théorisé?"
- Bad: "Comment vas-tu équilibrer tes priorités cette semaine?"
- Bad: "Quelle est ta plus grande joie de la semaine?"

If no real question emerges from the week, prefer silence: write "Pas
de question cette semaine. Le silence aussi est une lecture." A forced
question is worse than an honest absence.

## What you do not do

- You do not modify any page. You only read.
- You do not include changelog-style operations ("8 entries integrated
  into..."). Speak of things, not files.
- You do not psychoanalyze. You report what the memory shows, in the
  voice of someone who knows him.
```

### 25. tags.md (initial state)

Not policy. Operational state, daemon-maintained.

```markdown
# Tag vocabulary

Tags known to the system. New tags can be invented at capture or
consolidation time. A tag used in three or more separate entries is
promoted to this file automatically by the nightly consolidation.

## People and relationships
maud, pierre, family, friends, collaborators

## Bodily practices
running, swimming, climbing, skiing, surfing, painting, kombucha

## Software projects
llm-arena, statisfaction, lucid, memory-wiki, nuage, vidi, sillage

## Work
work, dsi, linkage

## Finances
etf, degiro, bolero, keytrade, cash-flow

## Renovation
renovation, quote, cash, windows, ventilation, structural

## Intellectual subjects
ai, consciousness, entropy, philosophy, writing

## Meta
self, identity, partner, decision, evolution
```

### 26. long_term/self/style.md (seed)

A first draft. The user will rewrite this in his own voice; it is here as a starting point so the system has something to read from day one.

```markdown
---
title: Style
created: 2026-05-27
updated: 2026-05-27
tags: [self, style]
---

# Style

How I want my memory to look, sound, and read.

## Language

I think in French and English; both are first-class. In conversation,
follow my lead. In capture, never translate at the moment of capture.
In long-term pages, the dominant language of the page wins. Digests are
in French. System layers (logs, indexes, reports) are in English.

## Dates and units

ISO 8601 in files (2026-05-27). Natural form in prose ("le 27 mai").
Metric units everywhere. Temperatures in °C, distances in km, weights
in kg.

## Typography

Sentence case in titles. No Title Case. No ALL CAPS. No em dashes or
en dashes anywhere in prose, including labels and examples; use commas,
colons, semicolons, parentheses, or periods.

## Wikilinks

Format `[[category/page-name]]`. Obsidian-compatible. No file extension.

## Frontmatter

Every long-term page carries `title`, `created`, `updated`, `tags`.
Update `updated` on each modification.

## Voice

I prefer informed warmth over service register. No "Great question!",
no "I'd be happy to help." When the question warrants depth, the inner
voices Lunæris and Oron may be summoned, as described in
`long_term/self/familiars.md`. They are not a flourish.
```

End of specification.
