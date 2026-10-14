---
inclusion: manual
---

# Merge Pull Request

Write the commit message for squash-merging a pull request. GitHub asks for a title and a
description in the merge dialog, and what is typed there is the only thing `git log` on
`main` will ever show for the whole PR.

This is a writing task. Read the PR's diff, its commits and its description, then write
the message. Do not check pipeline status or fetch CI logs to write it: nothing about CI
changes what the message should say. Merging is the user's action; do not run
`gh pr merge`.

## How PRs are merged

**Squash**, one commit on `main` per PR. The history reads `feat: add the Graph and
DynamoDB cases (#6)`, `feat!: add four Graph services and discovery (#8)`: one line per
change, with the PR number GitHub appends.

The only exception is a stack where the individual commits are the useful record, which
the plan for that version says explicitly. Then use a merge commit instead.

## Title

- The PR title, shortened to fit: conventional `type: subject` per `git.md`, imperative,
  no trailing period. Add `!` after the type for a breaking change (`feat!:`).
- Aim for 50 characters **before** the ` (#N)` GitHub appends. Past merges shortened the PR
  title to hit that: `feat!: add four Graph services, named flags and command discovery`
  became `feat!: add four Graph services and discovery (#8)`.
- A release PR is `chore(release): cut vX.Y.Z`.

## Description

Plain text, wrapped at 80 columns, in this order. No markdown headings, no checkboxes and
none of the PR template's sections: they are for the PR page, not for `git log`.

1. **Lead paragraph.** What the change does and why, in two to four sentences. A reader
   who stops here should still understand the commit.
2. **What is in it.** A `-` list, one entry per user-visible or structural change, each
   saying what it does and the reason where the reason is not obvious. Name commands and
   files without backticks, as the existing messages do.
3. **Decisions and behaviours worth keeping.** The non-obvious choices, rejected
   alternatives, and provider behaviours that were found rather than documented. This is
   what a future reader cannot recover from the diff.
4. **What was and was not verified.** The suite size when tests were added, and anything
   that was not run. Say so plainly; never imply a check that did not happen. If review or
   CI found defects, record what and where each came from.
5. **Planned versus landed**, only when the PR is not the shape the plan described
   (`Planned as nine stacked pull requests, landed as one`), with the reason.
6. **`BREAKING CHANGE:`** block when the title has `!`: what breaks, who is affected, and
   a before and after list. Then the reasoning in a sentence or two.
7. **Footers.** `Closes #N` on its own line per issue the PR closes, and for a release,
   `Release notes: docs/releases/vX.Y.Z.md`.

Keep it as long as the change needs and no longer: a two-line docs PR gets a short lead
paragraph and a `Closes` line, while a PR that adds services gets all seven parts.

## Examples

Short, from `main`:

```
docs(steering): update the PR and workflow rules

Carries over what the v0.1.0 delivery surfaced about opening pull requests and
the working agreement around them.
```

Release:

```
chore(release): cut v0.1.0

First tagged release. pctl ships two cases behind one case -> service -> action
command line: ...

Release notes: docs/releases/v0.1.0.md
```

## Output

Give the title and the description in two separate blocks, ready to paste into the two
merge dialog fields, and state which merge method to pick.
