# Write Feature Doc

## Objective

Create or revise a feature document in `docs/feats/` using the canonical spec in `docs/feats/_docs.md`.

The output should be consistent, implementation-truthful, and easy to maintain.

---

## Invocation

The user may provide:
- Feature/topic name (for example "scroll passthrough", "multi-cursor undo")
- Target file (for example `docs/feats/ui-scroll.md`)
- Mode: create new doc or update existing doc
- Optional scope hints (what to include/exclude)

If file/topic is missing or ambiguous, ask one concise clarifying question.

---

## Required inputs to resolve

Before writing, resolve:
1. Target doc path in `docs/feats/`
2. Feature boundary (what behavior this doc owns)
3. Whether this should be a focused doc or a hub doc

---

## Process

1. Read `docs/feats/_docs.md` and apply its required section order and writing rules.
2. Treat code as source of truth. Validate behavior against implementation files for the feature.
3. If updating an existing doc:
   - Preserve useful content.
   - Reorganize into canonical structure.
   - Remove stale or duplicate claims.
4. If creating a new doc:
   - Use the starter template from `docs/feats/_docs.md`.
   - Keep filename concise kebab-case and behavior-oriented.
5. Add/update cross-links in `## Related docs` to avoid duplicated deep detail.
6. Run the authoring checklist from `docs/feats/_docs.md` before finalizing.

---

## Section policy

Required sections (in order):
1. `# <Title>`
2. intro paragraph
3. `## Goal`
4. `## Scope`
5. `## User-facing behavior`
6. `## Architecture`
7. `## Key files`
8. `## Related docs`

Optional sections are allowed only when they add clear value (`Overview`, `Lifecycle`, `Debugging`, `Performance characteristics`, `Known risk areas`, `Manual QA`, `Non-goals`).

---

## Output format

Return:

```markdown
## Feature Doc Update

**Target:** `docs/feats/<file>.md`
**Mode:** [create | update]

### What changed
- [bullet]
- [bullet]

### Notes
- [Any unresolved ambiguity or follow-up]
```

Then apply edits directly to the target doc.

---

## Constraints

- Keep docs in `docs/feats/` implementation-truthful.
- Do not invent behavior to complete missing sections.
- Keep language concise and technical.
- Prefer links over repeated deep explanations.
- Follow relevant `.cursor/rules/` when documenting constrained behavior.

