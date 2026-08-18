---
inclusion: manual
---

# Release Notes Template

Use this structure for every release description, on **both GitLab and GitHub**.

Unlike PR and issue templates, neither forge auto-loads a release-notes template from
the repository, so there is **one shared copy** rather than a per-forge pair:

    docs/templates/release-notes.md

Copy it, fill it in, and pass it to whichever forge is in play. Keep it as a single file;
duplicating it per forge would only create two things to drift.

```markdown
# 🚀 vX.Y.Z – Release Name

## Overview

...

## Added

...

## Changed

...

## Fixed

...

## Related Work

### Milestone

...

### Pull Request

...

### Issues

...

## Notes

...

**Full Changelog**
```

## Filling it in

- **Heading** uses the real tag and a short release name: `# 🚀 v0.2.0 – Parallel Scan`.
  The tag must match the version in `pyproject.toml`.
- **Overview** is two or three sentences on what this release is for, written for someone
  deciding whether to upgrade.
- **Added / Changed / Fixed** follow [Keep a Changelog](https://keepachangelog.com/)
  semantics. Omit a section that has no entries rather than writing "none". Describe
  user-visible behaviour, so new commands and flags, changed output or exit codes, not
  internal refactors.
- **Related Work** links the milestone, the MR/PR and the issues closed.
- **Notes** carries anything that is not a code change: breaking changes and the
  migration step, new required permissions or environment variables, deprecations.
- **Full Changelog** takes the compare link between the previous tag and this one.

## Per forge

- **GitLab** — releases are tag-triggered. `.gitlab-ci.yml` builds `release_notes.md` in
  the `prepare_release_notes` job and the `create-release` job publishes the release.
  Pass the filled template as the release description rather than an inline string.
- **GitHub** — `gh release create <tag> --notes-file <file>`, using the filled template
  as the notes file. Use `--draft` when it needs review first.

Never write release notes inline on the command line: the headings, emoji and blank
lines do not survive shell quoting.
