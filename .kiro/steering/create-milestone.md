---
inclusion: manual
---

# Milestone Template

Use this structure for every milestone description, on **both GitLab and GitHub**.

Neither forge loads a milestone description template from the repository, so — like
release notes — there is **one shared copy** rather than a per-forge pair:

    docs/templates/milestone.md

Copy it, fill it in, and paste it into whichever forge is in play. Keep it as a single
file; duplicating it per forge would only create two things to drift.

```markdown
# Overview

Briefly describe the purpose of the milestone.

Explain how this milestone contributes to the Engineering Portfolio and how it aligns with the Documentation as Code philosophy.

---

# Objectives

- Objective 1
- Objective 2
- Objective 3
- Objective 4
- Objective 5

---

# Deliverables

## Repository

- Deliverable
- Deliverable
- Deliverable

## Documentation Layer

- Deliverable
- Deliverable
- Deliverable

## Generated Artifacts _(Optional)_

- Deliverable
- Deliverable

---

# Success Criteria

- Success criterion
- Success criterion
- Success criterion
- Success criterion

---

# Status

🚧 In Progress
```

## Filling it in

- **Title** is `vX.Y.Z – Milestone Name`, the same form `create-pr.md` expects in a PR's
  Milestone section. The version matches `pyproject.toml` or the next planned tag.
- **Overview** is a few sentences on why the milestone exists, then how it feeds the
  Engineering Portfolio and Documentation as Code.
- **Objectives** are outcomes, not tasks. The issues in the milestone are the tasks.
- **Deliverables** name concrete paths, split by layer: `Repository` for code and config,
  `Documentation Layer` for README, `docs/` and ADRs, `Generated Artifacts` for rendered
  diagrams and release notes. Drop the optional section rather than writing "none".
- **Success Criteria** are checkable conditions, not restated objectives. Include the
  verification that applies: `uv run ruff check .` clean, `uv run pytest -n auto` green
  with zero warnings, docs updated.
- **Status** stays 🚧 In Progress while the milestone is open, and becomes ✅ Complete
  when it closes.

## Per forge

- **GitLab** — create the milestone on the project's Milestones page, or with
  `glab api projects/:id/milestones`, passing the filled template as the description.
- **GitHub** — the Milestones tab, or
  `gh api repos/{owner}/{repo}/milestones -f title=... -F description=@<file>`.

Never write the description inline on the command line: the headings, emoji and blank
lines do not survive shell quoting.
