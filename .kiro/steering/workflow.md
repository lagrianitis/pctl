# Working agreement

## Stay in scope

Do exactly what was asked, nothing more. Unrequested improvements are not wanted.

- No drive-by refactors, renames, reformatting or "while I was in here" cleanups.
- No extra abstractions, options, error handling or tests beyond what the request
  needs. A bug fix does not come with surrounding code tidied up.
- Touch only the files the task requires.
- If you spot a genuine problem outside the request, mention it in one line and let
  the user decide. Do not fix it unasked.
- **Small config edits: just make the edit.** No codebase survey, no sub-agent, no plan
  document, no exploratory reads beyond the file being changed.
- **Copy the shape of an existing sibling file** instead of inventing structure. If a
  directory already has files of this kind, match their layout, front-matter and naming.

## Do not revert manual changes

Assume any edit you did not make was made deliberately by the user.

- Never undo, overwrite or "correct" manual changes unless explicitly asked to.
- This applies with extra force to changes outside the current prompt's scope: if a
  file or region has been edited by hand and is unrelated to the task, leave it
  exactly as it is.
- Re-read files before editing rather than writing from a remembered version, so
  manual edits are not clobbered by a stale rewrite.
- Prefer targeted edits over whole-file rewrites for the same reason.
- If a manual change appears to conflict with what was asked, say so and ask which
  should win instead of choosing silently.

## Naming

The employer's name never appears in generated content; use `Company` instead. Full rule
in `bt.md`.

## Hard limits

**Never run `git push`.** Not to any remote, not to any branch, not with any flag, not
even when a procedure in this repo says to and not even when asked to as part of a larger
request. Pushing is the user's action alone.

- Commit when asked, then **stop** and say the branch is ready to push. Report the branch
  name and commit hash so the user can push in one command.
- This overrides the push steps in `commit.md` and `create-pr.md`. Those procedures stop
  at the commit; the user pushes, then opening the PR/MR resumes.
- Also never do anything that pushes as a side effect: `git push --tags`,
  `gh pr create` / `glab mr create` on an unpushed branch, `git publish` aliases, or a
  release command that pushes a tag.
- Never `--force`, never rewrite published history. Not relevant while pushing is off the
  table, and it stays true if that ever changes.

**Never run local render or validate tooling.** Being installed on this machine is not
permission to use it.

**There is no local validation step.** Do not try to prove a change works by rendering
it. Do not add such a step, do not install tooling, do not write a wrapper script.
**CI is the validator.**

- Verify by **reading** the file you changed and the templates it must match, not by
  executing anything. See "Definition of done" below.
- This includes formatters, linters, renderers, schema and markdown validators, link
  checkers, diagram generators and ad-hoc `python -c` one-liners used as checks.
- **Even when you write tests, do not run them.** Writing a test and executing it are
  separate acts; only the first is implied by a request to add tests.
- **Do not run scripts unless you are explicitly asked to.** No "just checking it
  works", no smoke run, no `--help` invocation to confirm wiring.
- Report what you changed and what CI will check. Say plainly that you did not execute
  anything, rather than implying verification you did not perform.

**Always respect `.gitignore`.** An ignored path is outside the project as far as any
change is concerned. Allow the `.kiro/steering` listing

- Never create, edit or delete a file that matches an ignored pattern, and never stage one.
  No `git add -f`, no exception "just this once".
- Never commit generated or local-only paths: `.venv/`, `__pycache__/`, `.ruff_cache/`,
  `.pytest_cache/`, `*.pyc`, `dist/`, `build/`, `.env`, `.envrc`, `.coverage`.
- Treat ignored paths as disposable output, never as a source of truth. Read the source
  that produces them instead: `pyproject.toml` and `uv.lock`, not `.venv`.
- Exclude them when searching, so results describe the project rather than caches and
  vendored copies.
- If something the task genuinely needs is ignored, say so and let the user decide. Do not
  un-ignore it, and do not edit `.gitignore` to make room for it.
**Anything prefixed `IGNORE-` does not exist.** Any file or directory whose name starts
with `IGNORE-`, and everything beneath it at any depth, is completely out of bounds unless
the user names it in the request.

- Do not read, edit, create, delete, move or stage it.
- Do not search it, and exclude it from every glob and grep. It must not appear in results.
- Do not import from it, copy code out of it, or cite it as precedent for how this project
  does things. It is not a sibling to match.
- Do not count it when surveying the repo, and never report on its contents.
- The only exception is an explicit instruction naming the path. A generic "look at the
  whole repo" is not that, and neither is a wide search that happens to reach it.
- `IGNORE-helpers/` is the current instance: local reference material, gitignored via
  `IGNORE*`, excluded from ruff, and not part of the package.

### Definition of done

A change is done when it has been **read back and matches its siblings**: correct path,
same structure and front-matter as comparable files, placeholders filled, and internal
references pointing at paths that exist. Nothing is executed to reach that conclusion.
