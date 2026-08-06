# Deck — GDS API Schema Checker & Uplifter

Seven slides, content only. Design later. Lines prefixed `>` are speaker notes.

---

## Slide 1

**gds-api-schema-uplift**

A pre-commit check for the GDS API Standards, with an AI assistant that suggests the fix.

> Keep the intro short. It's a small local tool that runs before you commit. That's the whole shape.

---

## Slide 2 — The problem

The GDS API Standards are written as prose, so no computer can check them directly. Compliance ends up being caught at code review, or missed entirely. Every team writes their own version of the checks and they drift apart.

It matters more than it used to. AI agents now read OpenAPI specs directly to work out how to call an API. When the spec is off, it isn't just a review nit; the agent gives up.

> One sentence to land: standards without tooling are standards on paper.

---

## Slide 3 — What we built

The developer runs one command before committing:

```
$ gds-api-schema-uplift openapi.yaml
```

The tool parses the spec, checks it against the GDS and NCSC standards, and prints each issue alongside the exact clause it comes from. For anything that needs judgement, Claude proposes a concrete fix. The developer walks through the findings one at a time — accept, skip, edit, or quit. Nothing is written to disk without an explicit yes, and a backup is taken first.

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

Every AI suggestion cites the specific GDS or NCSC clause it's based on. If a suggestion turns up without a citation, we treat that as a bug in the tool.

Before the developer ever sees a proposed patch, we've applied it to a copy of the spec and re-validated. Anything that would break the spec is dropped silently and never rendered.

And no file is ever changed without a `y`. There is no auto-apply mode — that's a deliberate constraint, not something we haven't got to yet.

> If someone asks how we'd coach a junior on AI output, this slide is the answer.

---

## Slide 6 — What it changes

Compliance moves from a code-review problem to a before-you-commit problem, which is where it's cheapest to fix. A single shared clause map means teams stop diverging on interpretation. Juniors get the clause and the fix inline, instead of learning by red-pen feedback in review comments. And because every run emits telemetry, "did the check actually run" is a question with a real answer.

There's a second effect that wasn't the original pitch: a spec that meets the GDS standard is also a spec an AI agent can consume without hand-holding. That's the one that ages best.

> Don't dwell here. One breath per point, then land the agent angle at the end.

---

## Slide 7 — What's next

The obvious next step is a GitHub Action so the same checks run on every pull request as annotations. Beyond that, more rules — the v1 ceiling is the whole GDS standard, not just the subset we shipped this week. And ideally a shared clause map that gov teams contribute back to.

Not on the roadmap: a hosted service, auth, a dashboard, or an auto-apply mode. This stays a local tool.

> Thanks. Questions.
