# Rendered architecture diagrams

Return to [[Home]] · [[Architecture/Communication layers]] · [[Architecture/Write lifecycle]] · [[Architecture/Runtime and recovery]]

Twelve Mermaid blocks in the architecture and operations notes were rendered through the installed `tuios mermaid` command on 2026-11-04; on 2026-11-05 Scheduler Runbook diagrams 3 and 4 were added and all four Scheduler Runbook diagrams were re-rendered the same way after the job and notice-lifecycle changes, for fourteen exports in total. The resulting SVGs were parsed as XML; the overview PNG was visually inspected. This validates these exports, not Obsidian's own renderer or every future edit of a diagram.

`render-receipt.json` records the source note and its SHA-256, diagram number, output and output SHA-256; `tools/check.py` fails the diagrams gate when either hash is stale. Regenerate the corresponding export after a source diagram changes.

![[overview.png]]

- ![[communication-layers-1.svg]]
- ![[communication-layers-2.svg]]
- ![[write-lifecycle-1.svg]]
- ![[write-lifecycle-2.svg]]
- ![[runtime-and-recovery-1.svg]]
- ![[runtime-and-recovery-2.svg]]
- ![[reference-workflow-1.svg]]
- ![[reference-workflow-2.svg]]
- ![[reference-workflow-3.svg]]
- ![[scheduler-runbook-1.svg]]
- ![[scheduler-runbook-2.svg]]
- ![[scheduler-runbook-3.svg]]
- ![[scheduler-runbook-4.svg]]
- ![[ssh-state-1.svg]]

Reproduce a single export from the project directory:

```sh
tuios mermaid 'Collective.vault/Architecture/Communication layers.md' \
  --diagram 1 --format svg --out /tmp/collective-overview.svg
```
