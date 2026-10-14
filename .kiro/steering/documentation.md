---
inclusion: fileMatch
fileMatchPattern: "**/*.md,docs/**,**/README*,**/CHANGELOG*,**/ADR-*"
---

# Documentation & Diagrams

## Mandate

Every project must be documented well enough that another engineer can understand, deploy, and modify it without asking questions. Documentation is not an afterthought — it ships with the code.

## Required Documentation

### README.md (every project root)

Must contain:

1. **What**: One-paragraph description of what this project does and why
2. **Install**: Exact tools and versions needed (Python 3.14+, uv), and the install
   commands, including the optional `fast` and `azure` extras
3. **Configure**: Every environment variable, with a description and an example value,
   pointing at `.env.example` rather than repeating secrets
4. **Usage**: One section per command group with runnable examples, plus how to find a
   command (`pctl commands`, `pctl tree`)
5. **Output and exit codes**: The formats, the stdout/stderr split and the exit-code table
6. **Layout**: The case → service → action tree, kept consistent with `structure.md`
7. **Development**: Setup, the three test tiers and how to run them
8. **Security notes**: Token caching, what is masked, where credentials may come from

### Where else documentation lives

- `docs/wiki/` — user-facing pages, one per command group, plus `Common-Options`,
  `Output-and-Exit-Codes`, `Permissions` and `Troubleshooting`. A command, flag or
  required Graph permission that changes means the matching page changes.
- `docs/milestones/`, `docs/releases/` — one file per version, written from
  `docs/templates/milestone.md` and `docs/templates/release-notes.md`.
- `docs/plans/` — the PR plan for a version, recording divergences rather than leaving
  the plan wrong.

### Diagrams

- A diagram is worth adding when the data flow or command layout is hard to follow in
  prose. For this CLI the tree in `structure.md` and the README `Layout` section usually
  carry it; there is no network or VPC boundary to draw.
- Prefer text sources (Mermaid, ASCII) kept in the markdown they illustrate, so they are
  reviewed in the diff. Update them when the structure changes.

### Inline Documentation

- Every module must have a top-level docstring explaining its purpose
- Complex business logic must have comments explaining WHY, not WHAT
- Command docstrings are `--help` text: keep their `\b` examples accurate

### Decision Records

- For significant technical decisions, create a lightweight ADR in `docs/decisions/`
- Format: Context → Decision → Consequences
- Examples: "Why Graph v1.0 over beta for entitlement management", "Why moto over Stubber"

## When Creating or Modifying Code

1. Update the README if behavior changes
2. Update the matching `docs/wiki/` page if a command, flag or permission changes
3. Update the Layout tree if a package or module is added
4. Add/update inline documentation for new functions
