---
inclusion: manual
---

# Create Pull Request

Open a pull request for the current branch using the GitHub CLI.

**The branch must already be pushed by the user.** Pushing is a hard limit in
`workflow.md`. If the branch has no upstream, stop and ask the user to push it, then
continue from step 5.

## Process

1. Check branch name, recent commits, and changed files
2. Use your reasoning model: THINK HARD about what this change accomplishes, why it matters, and how to explain it clearly to reviewers
3. Write a PR title: type: short description

- feat | fix | refactor | docs | test | chore | perf

4. Write a concise body with:

- Summary: What and why (2-3 sentences)
- Changes: Key modifications (bullet list)
- Testing: How it was verified

5. Run gh pr create against the already-pushed branch — never push it yourself

## Final PR of a milestone

When the change being committed is the **last PR of a milestone** — its `Target Release`
is the version about to be cut, and nothing else in the milestone is outstanding — the
release version is updated on the same branch, in the same commit. Not as a follow-up.

- Bump `[project].version` in `pyproject.toml` to that version, then refresh `uv.lock`
  per `tech.md` so the lock records the same version. CI verifies the tag against
  `pyproject.toml`, so a stale version fails the `tag` job.
- Fill `docs/releases/vX.Y.Z.md` from `docs/templates/release-notes.md`, following
  `release-notes.md`. The final PR is the point where the real PR and issue numbers for
  `Related Work` exist, so complete that section rather than leaving placeholders.
- Flip `Status` in `docs/milestones/vX.Y.Z.md` from 🚧 In Progress to ✅ Complete, with
  the release link.
- Note any divergence from the plan in `docs/plans/vX.Y.Z-pr-plan.md` — PRs that merged
  together, or scope that moved — rather than silently leaving the plan wrong.
- **Tagging and publishing stay CI's job**, triggered by the release. Do not create a tag
  by hand, and do not push: the hard limits in `workflow.md` still apply.

If the milestone is not finished by this PR, leave the version alone. A version bump per
PR is exactly what this rule prevents.

## Notes

- Use --draft if not ready for review
- Use --base <branch> if not targeting the default branch
- Provide the PR URL when complete

## PR Body Template

The template is committed for both forges and the two copies are identical:

| Forge  | Path                                         |
| ------ | -------------------------------------------- |
| GitHub | `.github/PULL_REQUEST_TEMPLATE.md`           |
| GitLab | `.gitlab/merge_request_templates/Default.md` |

Read the body from whichever path exists rather than retyping it, and **when you change
one, change the other in the same commit.** GitLab only reads templates from the default
branch, so a template change has no effect until it merges.

Fill every section; delete none of the headings. Leave a checkbox unticked rather than
claiming something that was not done, and replace the `vX.Y.Z` placeholders with real
values or state that they are not yet known.

For reference, the shared content is:

```markdown
# Summary

Describe the purpose of this pull request.

---

## Changes

List the main changes introduced by this pull request.

-
-
- ***

## Validation

- [ ] Documentation reviewed
- [ ] Markdown formatting verified
- [ ] Links verified, if applicable
- [ ] Repository structure reviewed, if applicable
- [ ] Related issues linked

---

## Related Issues

Closes #

---

## Milestone

`vX.Y.Z – Milestone Name`

---

## Target Release

`vX.Y.Z`
```

Pass it via `gh pr create --body-file <file>` (or `glab mr create --description <file>`)
rather than an inline `--body`, so the headings, checkboxes and blank lines survive
shell quoting.
