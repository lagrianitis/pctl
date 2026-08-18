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

## Notes

- Use --draft if not ready for review
- Use --base <branch> if not targeting the default branch
- Provide the PR URL when complete

## PR Body Template

The template is committed for both forges and the two copies are identical:

| Forge | Path |
| --- | --- |
| GitHub | `.github/PULL_REQUEST_TEMPLATE.md` |
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
