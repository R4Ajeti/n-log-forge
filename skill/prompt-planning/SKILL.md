---
name: prompt-planning
description: Generate a saved implementation prompt before implementation when the user says "generate a prompt", "plan a prompt", or "next prompt". Number prompts sequentially with six digits and a lowercase snake_case title, including changes not covered by the latest prompt.
---

# Prompt Planning

## Plan before implementation

Run this workflow first when a prompt is requested. Inspect context and write the prompt artifact before changing application code, dependencies, configuration, or running implementation commands. A prompt-only request ends with the saved prompt; if the user also requests implementation, proceed only after the artifact is complete. Existing implementation authorization does not skip this ordering.

Reuse relevant existing skills by name/path instead of copying their instructions into the prompt. If the user also requests creation or revision of a prerequisite skill, finish that skill before the implementation prompt. Otherwise record missing guidance without inventing an unrelated skill-creation task.

## Locate the prompt sequence

1. Resolve the target project and read its instructions and current request. Use a user-specified prompt directory, otherwise the established prompt directory, otherwise `<project_root>/prompt/`. Keep separate projects' sequences separate; do not assume repository names, absolute paths, or branch names.
2. Inspect all numbered prompts belonging to this sequence, including its archives. Reserve every existing six-digit prefix, even when a legacy title uses a different format; report nonconforming names without renaming them. Report ambiguous or duplicate sequence numbers; use content and explicit references to resolve the baseline, asking only if materially unclear.
3. The next number is the highest existing numeric prefix plus one, **not the file count**. Start at `000001` when none exist, and never reuse gaps. Choose a descriptive action-and-subject title in lowercase snake_case, for example `000001_define_application_service_boundaries.md`.
4. New filenames must match `^[0-9]{6}_[a-z0-9]+(?:_[a-z0-9]+)*\.md$`: exactly six digits followed by `_` and a lowercase snake_case title. Do not use dates or seven-digit rollover. If `999999` is reached, request a new sequence location. Recheck the sequence immediately before writing and create a new file without overwriting another prompt; on a collision, rescan and increment.

The latest prompt is the highest-numbered existing prompt in the selected sequence, not the most recently modified file. Preserve prior prompts unless the user explicitly requests an edit to one.

## Account for everything not yet covered

Read the latest prompt and any earlier prompts it relies on. Compare their requirements with the current request, subsequent decisions, and actual project state. For a first prompt, use the current requested scope and observed state as the baseline.

For an existing sequence, inspect all relevant changes since its recorded baseline: committed changes, staged and unstaged edits, untracked files, additions, removals, renames, documentation, tests, configuration, and new or corrected requirements. Use the actual recorded revision when available; do not assume a default branch, `HEAD~1`, or that a clean working tree means nothing changed. Limit discovery to the selected project and task; inspect sensitive configuration by names and structure without copying secret values.

If Git or a recorded revision is unavailable, compare available prior artifacts, snapshots, prompt descriptions, and current files. State the evidence used and any uncertainty; do not invent a revision or claim complete change detection from timestamps alone.

Build a compact coverage table in the new prompt:

| Change / requirement | Evidence | Current state | Next action |
| --- | --- | --- | --- |
| Concise description | Prior prompt, relative file/symbol, revision, or user decision | Implemented, pending, superseded, or unknown | Verify, implement, investigate, or none |

Include every relevant change absent from or inconsistent with the latest prompt. Separate already-applied changes from work still needed so the next implementer does not repeat completed edits. Carry forward unfinished requirements without duplicating completed history. Link covered prior work as context; identify superseded requirements explicitly. If nothing is uncovered, say so. Generate an empty-delta prompt only if the user still requests a new prompt; do not invent work to fill it.

## Write an executable handoff

Adapt the prompt to the task while including:

- **Outcome and scope:** the requested result, target project, constraints, and exclusions.
- **Baseline:** previous prompt path/number or “first prompt,” observed revision or other comparison evidence, and working-tree changes not represented by that revision. Reference durable existing evidence; do not create an unsolicited repository dump.
- **Coverage:** the table above, relevant assumptions, and unresolved decisions.
- **Plan:** ordered, concrete changes with repository-relative targets when verified; label unverified paths or configurable values. Name applicable skills and dependencies without embedding their rules.
- **Acceptance and verification:** observable success conditions, appropriate checks, compatibility requirements, and the evidence the implementer should report. Distinguish checks already run from checks planned.

Write instructions as a task for the next implementer, using specific action verbs and sufficient context to work without the conversation. Keep implementation details only where needed to preserve behavior or constraints; do not add unrelated features or boilerplate sections.

Before handoff, verify the sequence number, filename, prior-prompt link, coverage, and separation of completed versus pending work. Return the saved prompt's path and a brief account of newly covered changes and any baseline limitations.
