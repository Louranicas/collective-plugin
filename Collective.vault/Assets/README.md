# Rendered architecture diagrams

Return to [[Home]] · [[Architecture/Communication layers]] · [[Architecture/Write lifecycle]] · [[Architecture/Runtime and recovery]]

Twelve Mermaid blocks in the architecture and operations notes were rendered through the installed `tuios mermaid` command on 2026-11-04; Scheduler Runbook diagrams 1 and 4 were re-rendered the same way on 2026-11-05 after the job and notice-lifecycle changes. The resulting SVGs were parsed as XML; the overview PNG was visually inspected. This validates these exports, not Obsidian's own renderer or every future edit of a diagram.

`render-receipt.json` records the source note, diagram number, output and output SHA-256. Regenerate the corresponding export after a source diagram changes.

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
- ![[ssh-state-1.svg]]

Reproduce a single export from the project directory:

```sh
tuios mermaid 'Collective.vault/Architecture/Communication layers.md' \
  --diagram 1 --format svg --out /tmp/collective-overview.svg
```
