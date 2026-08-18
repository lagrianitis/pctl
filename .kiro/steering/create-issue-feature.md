---
inclusion: manual
---

# Feature Issue Template

Use this template for every feature or milestone-task issue. All four sections are
required; fill them rather than leaving placeholder text. Title follows `[Area] ` — the
area being the case or component touched, for example `[azure] `, `[aws ddb] `,
`[output] `.

The template is committed for both forges:

| Forge | Path | Format |
| --- | --- | --- |
| GitHub | `.github/ISSUE_TEMPLATE/feature.yml` | issue form (YAML) |
| GitLab | `.gitlab/issue_templates/Feature.md` | markdown description template |

GitLab has no issue-forms equivalent, so the two cannot be one file. They must stay
**semantically identical**: same five sections, same order, same title convention, same
`feature` label. Change one, change the other in the same commit. GitLab only reads
templates from the default branch, and applies the label via the `/label ~feature` quick
action at the end of the file.

The GitHub source of truth:

```yaml
name: Feature
description: Plan a new feature or milestone task.
title: "[Area] "
labels:
  - feature
body:
  - type: textarea
    id: summary
    attributes:
      label: Summary
      description: Describe the feature or task.
    validations:
      required: true

  - type: textarea
    id: objectives
    attributes:
      label: Objectives
      description: What should this work achieve?
      placeholder: |
        - Objective 1
        - Objective 2
    validations:
      required: true

  - type: textarea
    id: deliverables
    attributes:
      label: Deliverables
      description: What files, documents or outputs should be created or changed?
      placeholder: |
        - `path/to/file.md`
    validations:
      required: true

  - type: textarea
    id: acceptance
    attributes:
      label: Acceptance Criteria
      description: What conditions must be met for this issue to be complete?
      placeholder: |
        - [ ] Criteria 1
        - [ ] Criteria 2
    validations:
      required: true

  - type: input
    id: target-release
    attributes:
      label: Target Release
      placeholder: v0.2.2
```

## When filling it in

- **Deliverables** name concrete paths. For a new action that means the action module,
  the `LAZY_SUBCOMMANDS` entry, and the mirrored test module in each tier, per
  `structure.md`.
- **Acceptance Criteria** are checkable conditions, not restated objectives. Include the
  verification that applies: `uv run ruff check .` clean, `uv run pytest -n auto` green
  with zero warnings, and README updated if behaviour changed.
- **Target Release** matches the version in `pyproject.toml` or the next planned tag.
  Releases here are tag-triggered, so this is what the tag will be.
