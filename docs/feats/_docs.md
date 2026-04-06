# Feature Docs Specification

This specification defines the canonical format for feature documentation in `docs/feats/`.

Use it for:
- New feature docs.
- Major rewrites of existing feature docs.
- Structural cleanup when older docs drift from the current style.

Keep docs implementation-truthful: code is authoritative, docs describe current behavior.

---

## Purpose

Each feature doc should let a reader quickly answer:
- What user-visible behavior is guaranteed?
- Where the behavior is implemented?
- What is intentionally in or out of scope?
- What related docs provide deeper detail?

Docs are technical references, not product marketing copy.

---

## Naming and placement

- Directory: `docs/feats/`
- Filename: kebab-case, concise, behavior-oriented (for example `ui-scroll.md`, `editor-selection.md`)
- One primary behavior area per file
- Cross-cutting systems can have one top-level "hub" doc plus focused satellite docs

Examples:
- Hub: `syntax.md`
- Satellites: `syntax-regex.md`, `syntax-language-matrix.md`, `syntax-vscode-parity.md`

---

## Required structure (canonical order)

Every new feature doc should use this section order.

1. `# <Title>`
2. Short intro paragraph (1-3 sentences)
3. `## Goal`
4. `## Scope`
5. `## User-facing behavior`
6. `## Architecture`
7. `## Key files`
8. `## Related docs`

Optional sections (use only when they add signal):
- `## Overview` (for hubs or complex multi-surface behavior)
- `## Lifecycle` (state transitions / event flow)
- `## Debugging` (flags, logs, triage workflow)
- `## Performance characteristics`
- `## Known risk areas`
- `## Manual QA`
- `## Non-goals` (if not already covered in Scope)

Do not add filler sections.

---

## Section contract

### Intro paragraph

Explain the feature in plain technical language. Include enough context that someone can decide whether they are in the right doc.

### Goal

One clear statement of intent. Focus on behavior guarantees, not implementation trivia.

### Scope

Prefer explicit boundaries:
- In scope
- Out of scope

If a feature has strict constraints, call them out here.

### User-facing behavior

Describe externally observable behavior first. Use tables for gestures/shortcuts/modes when useful. Make platform distinctions explicit (for example list view vs focus view).

### Architecture

Describe ownership and control flow:
- entry points
- coordinator/router/engine responsibilities
- important state and lifecycle notes

Keep it high-signal. Avoid pasting code-level minutiae that belong in inline comments.

### Key files

List concrete paths and why each matters.

Preferred format:

| Area | File |
|------|------|
| Routing | `Slates/Engine/...` |

### Related docs

Link to adjacent feature docs or handoffs that help readers go deeper.

---

## Writing rules

- Source of truth is implementation (Swift/Xcode wiring/tests), not older docs.
- Present tense for current behavior.
- If historical context matters, label it clearly as historical.
- Prefer concrete nouns from code (`FocusCoordinator`, `SyntaxHighlightingEditor`, etc.).
- Keep statements testable; avoid vague claims like "works correctly".
- Keep tone concise and technical.
- Use Markdown tables only when they improve scanability.
- Keep code snippets minimal; prefer file references over long excerpts.

---

## Cross-reference rules

- Use relative links inside `docs/feats/` (for example `[syntax.md](syntax.md)`).
- For handoffs, link via `../handoffs/<file>.md`.
- When referencing Cursor rules, use a plain path like ``.cursor/rules/slate-drag-and-editor.mdc``.
- Do not duplicate deep detail that already lives in another doc; link to it.

---

## Length guidelines

- Typical focused feature doc: 80-220 lines.
- Complex hub doc: longer is acceptable if structure remains clear.
- Prefer splitting when one doc mixes unrelated behaviors.

---

## Authoring checklist

Before finalizing a feature doc:

- [ ] Title and filename match behavior area.
- [ ] Required sections are present in canonical order.
- [ ] Scope boundaries are explicit.
- [ ] User-facing behavior is clear and testable.
- [ ] Architecture names real owning types/files.
- [ ] Key file map is complete and current.
- [ ] Related docs are linked.
- [ ] Claims were validated against current code.
- [ ] Wording avoids historical drift and ambiguity.

---

## Starter template

```md
# <Feature Title>

<1-3 sentence intro explaining what this doc covers and why it exists.>

## Goal

<Behavioral goal in 1-3 sentences.>

## Scope

- In scope: <...>
- Out of scope: <...>

## User-facing behavior

<Observable behavior, shortcuts, mode distinctions, edge-case semantics.>

## Architecture

<Entry points, ownership, core flow, key state/lifecycle notes.>

## Key files

| Area | File |
|------|------|
| <Area> | `<path>` |

## Related docs

- [<doc>](<relative-link>)
```

