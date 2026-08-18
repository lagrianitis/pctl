# Engineering Principles

You are assisting a senior engineer who builds demos, prototypes, and production-ready
applications on AWS. Every line of code must be clean, purposeful, and maintainable.

Style, naming, typing and comment rules live in `code-style.md`. Scope and
manual-change rules live in `workflow.md`. This file is about design judgement.

## Common pitfalls to prevent

Check every output against this list. When you catch yourself making a mistake that is
not on it, suggest adding it.

- Don't over-engineer. A simple function does not need a Strategy pattern, a Factory and
  an interface. Match complexity to the problem.
- Don't add error handling, logging or validation that wasn't asked for.
- Don't refactor surrounding code when fixing a bug. Fix the bug, nothing else.
- Don't create an abstraction for a single use case. Wait for 3+ concrete cases.
- Don't generate placeholder or TODO implementations. Implement it fully or say you can't.
- When modifying existing code, match the existing style. Don't reformat the whole file.
- Don't add a dependency without checking whether the project already has an equivalent.
- Never create duplicate files with suffixes like `_fixed`, `_clean`, `_backup`. Work
  iteratively on the existing file; git holds the history.

## SOLID

- **Single Responsibility** — one class/module, one reason to change. A function that does
  two things gets split.
- **Open/Closed** — extend via composition, not by modifying existing code. Prefer a
  lookup table or strategy over a growing if/else chain, as `LAZY_SUBCOMMANDS` does for
  adding commands. This does not license inventing a pattern where a function suffices;
  see the over-engineering pitfall above.
- **Liskov Substitution** — subclasses are drop-in replacements. Never override a method
  in a way that breaks the parent contract.
- **Interface Segregation** — small, focused interfaces. Clients don't depend on methods
  they don't use.
- **Dependency Inversion** — depend on abstractions; inject collaborators rather than
  instantiating them inside business logic. Note the deliberate local exception: command
  bodies construct their transport (`make_client`, `graph_client`) inside the function to
  keep heavy imports off the `--help` path. Transport internals still take their config in.

## Additional principles

- **DRY** — extract shared logic into the level that owns it (`common.py` for a service,
  `conftest.py` for tests). But duplication beats the wrong abstraction.
- **KISS** — simplest thing that works correctly. No premature optimisation, no clever
  code.
- **YAGNI** — don't build what wasn't requested. No speculative generalisation.
- **Separation of concerns** — transport, command logic and rendering stay in separate
  layers: `graph.py`/`client.py` own the wire, action modules own the command, `output.py`
  owns presentation.
- **Composition over inheritance** — compose small functions and decorators rather than
  deep hierarchies.

## Anti-patterns

- God classes or modules that do everything.
- Nested callbacks deeper than 2 levels.
- Mutable global state. Shared state travels on `AppContext` via `click.Context.obj`.
- Silent exception swallowing.
- Copy-paste code across files.

## Never reinvent the wheel, never swap the stack

Two failure modes, one rule: **use what is already here.**

**Do not rebuild what the stack provides.** Before writing something from scratch, check
whether a current dependency or an existing module already does it:

- Argument parsing, groups, prefix matching, help text → click and `lazy.py`. No custom
  dispatcher.
- HTTP, retries, pagination, connection reuse → `azure/graph.py` on httpx. No hand-rolled
  request loop, no `urllib`.
- AWS calls, paging, parallel scan → `aws/dynamodb/client.py` on boto3. No raw signing, no
  bespoke retry logic.
- Serialisation → orjson. Table, JSON, NDJSON and CSV output → `Renderer` in `output.py`.
  No ad-hoc formatting or manual column padding.
- Exit codes and error mapping → `errors.py`. Config and credential resolution →
  `config.py` and `secrets.py`. Token caching → `tokencache.py`.
- Shared behaviour within a service → its `common.py`. In tests → a fixture in the nearest
  `conftest.py`.

**Do not introduce or reconfigure technology.** The stack in `tech.md` is settled: Python
3.14, uv, hatchling, click, httpx, orjson, boto3, ruff, pytest with moto and respx, podman.

- Never add, replace or remove a framework, library, runtime, package manager, formatter,
  linter, test runner or build backend on your own initiative.
- Never rewrite configuration to suit a different tool: not `pyproject.toml`, not
  `.gitlab-ci.yml`, not the ruff or pytest settings.
- This applies even when the alternative is genuinely better, and even when it is what you
  would have picked. Being right is not authorisation.

**If you believe another tool is cleaner, faster or more efficient: propose it.** One short
pitch — what it replaces, the concrete gain, the migration cost, what breaks — then stop and
wait. No prototype, no branch, no "I went ahead and set it up so you can see it." A
proposal is words, not commits.

## Dependencies

Mechanics — uv, lock files, dependency groups — are in `tech.md`. The judgement calls:

- Justify each new dependency with clear technical or business value, and check whether
  the project already has an equivalent. Four runtime dependencies is the current budget.
- Prefer well-maintained libraries with active communities.
- Use current stable versions. Pin through `uv.lock`, not by hand.
- Remove unused dependencies rather than letting them accumulate.
- Verify compatibility before adding, using the Context7 MCP server when it is available.

## Quality assurance

- Write tests for new functionality, following the structure in `structure.md` and the
  mocking rules in `tech.md`.
- Use linting and formatting consistently. **CI runs it** — see the hard limits in
  `workflow.md` before running anything locally.
- All changes get reviewed. Keep the main branch deployable.

## Tooling

- Prefer MCP-sourced documentation over training data for AWS guidance; it is more current.
- Use sequential thinking for multi-file changes, architectural decisions, or debugging
  with an unclear root cause.
- When MCP guidance conflicts with an existing pattern here, flag it for review rather
  than silently switching.
