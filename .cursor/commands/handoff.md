# Create Handoff Document

## Objective

Output a single handoff document into `docs/handoffs/` for another agent or session. Use date-coded, lowercase file naming.

## Output Location and Naming

- **Path**: `docs/handoffs/`
- **Format**: `YYYYMMDD_<topic-slug>.md` (e.g. `20260315_scroll-passthrough-arch-revision.md`)
- **If multiple handoffs for the same date exist**: Use letter suffixes: `20260315b_`, `20260315c_`, etc.

## Steps

1. **Determine filename**: Use today's date (YYYYMMDD) and a lowercase slug for the topic. Check `docs/handoffs/` for existing files with the same date+slug; if present, use the next letter suffix (`b`, `c`, …).
2. **Gather context**: From the current conversation or user input, collect:
   - Problem and reproduction steps
   - What was tried and why it failed
   - Relevant files, APIs, constraints
   - Success criteria
   - Any references (docs, forums)
3. **Write the document**: Follow the structure in `.cursor/rules/handoff-documents.mdc` (required and extended sections as applicable).
4. **Output**: Write the single file to `docs/handoffs/<filename>.md`.

## Output

- One handoff document at `docs/handoffs/YYYYMMDD_<topic-slug>.md` (or `YYYYMMDDb_`, etc. if duplicates exist)
- Confirm the path used
