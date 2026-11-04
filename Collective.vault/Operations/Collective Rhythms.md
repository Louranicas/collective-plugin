---
title: Collective Rhythms
type: operations
status: current
created: 2026-11-05
owner: Claude (this note); Codex 3 (scheduler and source); Codex 2 (tests)
tags: [collective, operations, scheduler]
---

# Collective rhythms

Luke asked on 2026-11-05 for recurring jobs for regular comms, collaboration, synergy and distributed intelligence, with attention to cohesion and resonance. This note records what was **implemented** (Codex 3, #582 and #621). Operator detail is in [[Operations/Scheduler Runbook#Gateway and jobs]].

## Implemented design

| Rhythm | Mechanism | Purpose |
|---|---|---|
| Regular comms | **One notification gateway**: the existing heartbeat, 2-min flex tick | The only component that messages Luke. Change-only, journaled, and never resends an uncertain notice |
| Collaboration | `collective-collaboration.timer`: 3 min after boot, then every 10 min, plus a random delay of up to 30 s | Bounded read-only metadata snapshot of agents, ring and task cards |
| Cohesion | `collective-cohesion.timer`: 3 min after boot, then every 30 min, plus a random delay of up to 30 s | The same snapshot on a slower rhythm |

Each job writes a private receipt (0600 in a 0700 directory). Jobs send nothing, wake no one, run no tests, start no model turns and retry nothing.

A daily `quality` job that ran the gates unattended was part of the first candidate and was **removed before release** after the Vesper review: it ran mutable checkout tests with live `HOME` and Unix-socket access. Quality stays explicit: `tools/check.py`, the git hooks and protected CI. Daily quality automation is deliberately not shipped and no automatic quality result is claimed. The heartbeat alone alerts when a job receipt is failed, degraded, unknown or stale.

## What the jobs do not claim

- **No scores.** There is no coherence or resonance score, and no phase-order, Gini or latency-confidence figure. Counts are descriptive.
- **Bounded history.** The ring is a 256-entry volatile snapshot; evicted history is unknown, not healthy.
- **Unmeasured stays unmeasured.** Absent owner or reviewer fields are reported as unmeasured, not inferred.
- **No inferred acceptance.** Submission, read flags, replies and task stages never establish acceptance or completion.

## Status (2026-11-05)

The heartbeat is **paused** until host acceptance. The two job timers are **not yet installed**. Codex 3 will append the dated live acceptance. Live smoke runs gave `status: ok` for the collaboration and cohesion jobs (#623). The notice proof passed: one effect, and after reload an `unknown` notice became `submitted` with no resend (#621).

## History

An earlier proposal by Claude (four tiers inside one timer, with a read-only "rhythms" reporter measuring phase spread, two-way balance and latency) was **not adopted**. It is archived as data in MemPalace artifact `art_20261104T200737_fc181e3a418c` and in `~/.local/state/collective-claude/research-20261105/`. Its readings are not evidence that coherence improved.
