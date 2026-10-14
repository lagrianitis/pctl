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
  required Graph permission that changes means the matching page changes. Published to the
  GitHub wiki by CI; see "Wiki" below.
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

## Wiki

A GitHub wiki is always a separate git repository (`<repo>.wiki.git`); it cannot read a
folder of the main repository. The project keeps the pages in `docs/wiki/` and lets CI
mirror them into the wiki repository, so the pages are reviewed and versioned with the
code and the wiki repository never needs a human.

### Best practices

- **One source of truth.** Edit `docs/wiki/` only. The sync is `rsync --delete`, so
  anything edited in the Wiki tab, or any page that exists only there, is overwritten or
  removed on the next published release.
- **The wiki describes the latest release, not `main`.** A wiki has exactly one live
  version and no way to host a version per pull request or per branch, so it is published
  from the release tag. Documentation for unreleased work stays in `docs/wiki/` on `main`
  until the release that ships it.
- **Never push to the wiki repository by hand.** Its default branch is `master` and only
  that branch is rendered; other branches there are not shown in the Wiki tab. CI is the
  only writer.
- **Flat directory.** A wiki page is addressed by its file name alone, so no
  subdirectories. Names use hyphens, which the wiki shows as spaces: `Azure-Groups.md`
  is "Azure Groups".
- **Reserved files.** `Home.md` is the landing page, `_Sidebar.md` the navigation shown on
  every page, `_Footer.md` an optional footer. Every page should be reachable from
  `_Sidebar.md`.
- **Wiki-style links.** Link by page name without an extension, with an optional anchor:
  `[Groups](Azure-Groups#members)`. A link ending in `.md` works in the repository view but
  is a dead link in the wiki. CI fails the build on a link to a page that does not exist;
  it does not check anchors.
- **A command change changes its page in the same PR.** That is the "ships with the code"
  rule applied to the wiki.
- **No secrets and no real tenant data.** The wiki of a public repository is public, and a
  mirrored page is exactly as visible as the repository itself.
- **Restrict who can edit the Wiki tab** (repository settings, Features, Wikis), since
  edits there do not survive.

### One-time setup

1. Repository Settings, General, Features: tick **Wikis**.
2. Open the **Wiki** tab and choose **Create the first page**. Save anything; it is
   replaced by `Home.md` on the first sync. This creates `<repo>.wiki.git`, and there is no
   API to do it from CI. Until it is done the `wiki` job fails with a message saying so.
3. Settings, Actions, General, Workflow permissions: the `wiki` job asks for
   `contents: write` itself, so that works unless an organisation policy forces read-only.
   If the push is rejected, that policy is the cause.
4. Do steps 1 and 2 **before** opening a pull request that touches `docs/wiki/`: the
   `wiki` job runs on that pull request and cannot clone a wiki that does not exist.
5. Merge, then publish a release. The `wiki` job publishes the `docs/wiki/` of the
   release tag.

### How CI handles it

The `wiki-changes` and `wiki` jobs in `.github/workflows/ci.yml`:

- **Pull request touching `docs/wiki/`:** validates the pages (`Home.md` present, flat
  layout, no broken page links), clones the real wiki, and writes the would-be changes to
  the job summary. Nothing is pushed. A preview branch in the wiki repository was
  considered and rejected: the wiki UI only renders `master`, so such a branch could not be
  viewed, and it would be as public as the repository.
- **Merge to `main`:** nothing happens to the wiki.
- **Release published:** always runs against the release tag, commits the difference to
  the wiki repository as `github-actions[bot]` and pushes. It is idempotent, so a release
  with nothing to change pushes nothing, and a missed release is repaired by the next one.
  A pre-release also triggers it.

## When Creating or Modifying Code

1. Update the README if behavior changes
2. Update the matching `docs/wiki/` page if a command, flag or permission changes
3. Update the Layout tree if a package or module is added
4. Add/update inline documentation for new functions
