---
inclusion: manual
---

# Commit

Create a well-crafted git commit for the current changes.

## Process

1. Run `git status` and `git diff --staged` (and `git diff` if nothing staged)
2. Analyze the changes deeply:
   - What files changed and why?
   - What's the single unifying purpose?
   - What would a future developer need to understand?
3. THINK HARD: Write a commit message that future you will thank you for
4. Stage relevant files if needed
5. Commit with the crafted message
6. **Stop. Do not push** — see the hard limit in `workflow.md`. Report the branch and
   commit hash so the user can push.

## Commit Message Format

The conventions live in `git.md` (always loaded): conventional format, allowed types,
imperative mood, 50-character subject. This procedure adds only the detail specific to
writing one:

```
<type>: <subject>

<body>

<footer>
```

- **Subject** — complete the sentence "This commit will...". No trailing period.
- **Body** (required for non-trivial changes) — wrap at 72 characters, blank line after
  the subject, bullets for multiple points. Explain WHAT and WHY; the code shows HOW.
- **Footer** (optional) — `Closes #123` / `Refs #456`, and
  `BREAKING CHANGE: <description>` where it applies.

## Examples

**Simple:**
```
docs: add CLAUDE.md with workflow guidance
```

**With body:**
```
feat: add three-step workflow commands

Introduce plan/build/pr commands that structure development into
discrete phases. This separation ensures:

- Plans are reviewed before execution
- Builds follow explicit specifications
- PRs have consistent, thorough descriptions

The workflow reduces context-switching and improves code review quality.
```

## Output

Confirm the commit hash and the branch it landed on, and state that pushing is left to the
user.
