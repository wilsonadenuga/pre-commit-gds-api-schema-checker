# Deck — GDS API Schema Checker & Uplifter

Seven slides, content only. Design later. Lines prefixed `>` are speaker notes.

---

## Slide 1

**gds-api-schema-uplift**

- A CLI tool that runs as a pre-commit hook when you're building a GDS API
- Assists the developer with the GDS Standard before they push a commit

> Keep the intro short. It's a small local tool that runs before you commit. That's the whole shape.

---

## Slide 2 — The problem

- The GDS API Standards are written as prose — no computer can check them directly
- Compliance gets caught at code review, or missed entirely
- Every team writes its own version of the checks, and they drift apart

**It matters more than it used to:**

- AI agents now read OpenAPI specs directly to work out how to call an API
- When the spec is off, it isn't a review nit — the agent gives up

> One sentence to land: standards without tooling are standards on paper.

---

## Slide 3 — What we built

The developer runs one command before committing:

```
$ gds-api-schema-uplift openapi.yaml
```

- Parses the spec and checks it against the GDS and NCSC standards
- Prints each issue alongside the exact clause it comes from
- Where judgement is needed, Claude proposes a concrete fix
- The developer walks the findings one at a time — accept, skip, edit, or quit
- Nothing is written to disk without an explicit yes, and a backup is taken first

> This is the human-in-the-loop point. Coach, not gate. Say it once, move on.

---

## Slide 4 — Demo (~2 minutes)

*Live run against a deliberately broken spec.*

> Show the file first so people see what "broken" looks like.
> Run the tool. First finding: clause quoted, diff shown. Press `y`.
> Press `n` on the next one to prove you can say no.
> Press `e` on one to prove you can edit.
> End on the cost summary at the bottom of the run.

---

## Slide 5 — Why you can trust it

- Every AI suggestion cites the specific GDS or NCSC clause it's based on
- A suggestion without a citation is treated as a bug in the tool
- Every proposed patch is applied to a copy and re-validated *before* the developer sees it
- Anything that would break the spec is dropped and never rendered
- No file is ever changed without a `y`
- There is no auto-apply mode — a deliberate constraint, not a gap

> If someone asks how we'd coach a junior on AI output, this slide is the answer.

---

## Slide 6 — What it changes

- Compliance moves from a code-review problem to a before-you-commit problem — where it's cheapest to fix
- One shared clause map, so teams stop diverging on interpretation
- Juniors get the clause and the fix inline, instead of red-pen feedback in review comments
- Every run emits telemetry, so "did the check actually run" has a real answer

**The effect that wasn't the original pitch:**

- A spec that meets the GDS standard is also a spec an AI agent can consume without hand-holding
- That's the one that ages best

> Don't dwell here. One breath per point, then land the agent angle at the end.

---

## Slide 7 — What's next

- A GitHub Action, so the same checks run on every pull request as annotations
- A VS Code extension, so findings surface as squigglies in the editor before the commit hook ever fires
- More rules — the v1 ceiling is the whole GDS standard, not the subset we shipped this week
- A shared clause map that gov teams contribute back to

**Not on the roadmap:**

- A hosted service, auth, or a dashboard
- An auto-apply mode

This stays a local tool.

> Thanks. Questions.
