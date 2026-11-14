# Ruffster architecture and experience review

Reviewed: 2026-11-14

## What is working well

- The shared Python core keeps event validation, retention, schedule logic, encryption, and report math separate from macOS and Windows collection adapters.
- Native session indicators are part of the monitoring lifecycle. Sampling waits for the indicator to be ready and stops if its heartbeat disappears.
- The encrypted event log and memory-only report projection avoid leaving decrypted activity in a persistent parent database. The UI distinguishes measured counters from sampled estimates and states what missing data cannot explain.
- Family-facing pages and synthetic dashboard captures describe the current limits instead of implying complete coverage.

## Findings and next engineering steps

### 1. Report generation is the main scaling risk

`family_activity/parent_app.py` rebuilds a decrypted in-memory projection when producing a report, then selects activity rows and calculates summaries in Python. This keeps decrypted history out of persistent storage, which is a useful privacy property, but makes every report refresh do work proportional to retained history. It also temporarily holds the projection and selected rows in memory.

**Recommendation:** Keep the current privacy boundary for the first family release. Add a benchmark with a realistic 365-day, multi-device report before changing it. If it becomes slow, first reduce duplicate queries and avoid selecting unused columns. Consider an explicitly short-lived in-memory projection only after documenting its lifetime and clearing it on lock; do not add a plaintext disk cache.

### 2. `parent_app.py` has too many responsibilities

The 900-line module contains the loopback HTTP server, request validation, setup and key-transfer routes, import/merge logic, retention, and report assembly. This increases the chance that a UI endpoint change accidentally affects encryption, lifecycle, or local-network behavior.

**Recommendation:** Split only when the next backend feature needs a clean seam. A low-risk first boundary is `report_service.py` for `_report` and report database projection helpers, followed by route handlers grouped around setup, reports, and transfer. Keep `ParentServer` ownership of unlock state and nearby-share lifecycle in one place. Add route-level tests before moving code; avoid a broad mechanical split right before a family install.

### 3. Native platform behavior still needs device checks

The Python core and hosted builds can validate interfaces and packaging, but not the macOS login, sleep/wake, local-network permission, or Windows interactive tray/task behavior on family computers. Treat those as open validation items; do not turn a successful build into a product-readiness claim.

**Recommendation:** Maintain one concise per-platform acceptance checklist with real-device results and the supported OS version. Mac remains first priority, followed by Windows; Linux remains a development host.

### 4. Parent onboarding should feel like a guided welcome

The existing sequence is clear and honest, but its first screen is long and presents recovery, security detail, pairing, and report return close together. The former minimal visual styling also made it feel like a settings form rather than a family companion.

**Changes in this review:** refreshed the parent dashboard visual system with warmer paper tones, forest greens, serif display headings, clearer cards and step states, larger touch targets, and responsive layouts. Updated the mascot and Mac icon to a white/cream Golden Retriever. Increased muted text contrast after the automated checker flagged the initial palette.

**Next UX work:** test the first-run flow with a parent who has not seen the project. Consider introducing parent access and recovery as a short two-screen flow, then reveal child setup after the recovery copy is saved. Keep the existing explanations available in context. The setup screen should answer, in this order: what Ruffster observes, what it never observes, what the child can see, and what the parent does next.

### 5. Website collection remains optional and easy to misread

The dashboard already explains that the browser add-on runs on the child's computer, can be paused, and does not provide complete browsing coverage. This is honest, but the current explanation is lengthy and can distract from the working app and network summary.

**Recommendation:** Keep website details collapsed by default and label the feature as optional in the setup guide. Do not imply that app or network totals identify a website. Build the integration only when installation, visible status, and data freshness can be explained in one short flow.

## Refactoring decision

No broad backend refactor is justified from this review alone. The best immediate improvement is the dashboard presentation and matching dog artwork. The backend split and report-scaling work should be driven by focused tests and a repeatable benchmark, preserving the current memory-only decryption behavior unless measurements show it is insufficient.
