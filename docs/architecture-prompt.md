# Design brief — architecture diagram for the stakeholder slide

Paste the prompt below into a design tool (Claude, Figma AI, Excalidraw AI,
Miro AI, etc.). It's self-contained: someone with no context on this repo
should be able to render a usable slide diagram from just the text.

The output must be a **standard architecture diagram** — the kind an
engineering team would recognise from any well-run architecture review.
That means: named boxes for components, explicit boundaries between the
system and its external actors, arrows labelled with what flows over them,
and a consistent notation throughout. Not an infographic, not a metaphor,
not a "AI does magic" spider chart.

---

## The prompt (copy from here)

> Design a standard architecture diagram for a slide. Follow the conventions
> of a **C4-style System Context / Container diagram**: external actors sit
> outside the system boundary, the system itself is a labelled container
> holding its internal components, arrows carry a labelled data flow.
>
> **System name:** `gds-api-schema-uplift`
>
> **One-liner (for the diagram's subtitle):** A pre-commit guardrail for
> developers building GDS-standard APIs. Reads an OpenAPI spec, checks it
> against GDS + NCSC standards, and proposes AI-generated fixes that the
> developer approves interactively before anything is written to disk.
>
> **Audience:** UK Government / enterprise stakeholders. The diagram should
> read in three seconds at a glance, then reward a second read with more
> detail on the internal components.
>
> **Notation conventions (must follow):**
>
> - External actors (developer, code reviewer, team lead) drawn as
>   stick-figure people or rounded rectangles labelled as roles, outside
>   the system boundary.
> - The system itself is one large labelled container. Its internal
>   components are stacked rectangles inside that container.
> - External systems the tool integrates with (Anthropic API, SigNoz) are
>   separate containers on the outside, connected to the system by named
>   arrows.
> - Data stores (developer's `openapi.yaml`, JSONL event log) drawn as
>   the traditional cylinder shape.
> - Arrows are directional and every arrow is labelled with what flows
>   over it (e.g. "findings", "cited patches", "USER/APPROVES events").
> - No unlabelled arrows, no icons standing in for text.
>
> **Layout:** left-to-right primary flow. The developer sits on the left,
> the system in the middle, outputs on the right. External systems
> (Anthropic, SigNoz) sit above or below the tool with clearly labelled
> connections.
>
> **Elements — inside the system container (three components, stacked
> top-to-bottom in this order):**
>
> 1. **Deterministic rule engine** — subtitle: "11 rules · GDS + NCSC ·
>    no AI, no network"
> 2. **Claude agent** — subtitle: "Sonnet 4.6 · prompt caching ·
>    proposes RFC 6902 patches with clause quotes"
> 3. **Approval loop** — subtitle: "Human-in-the-loop · y / n / w / q ·
>    backup before first mutation"
>
> Arrows inside the container: (1) → (2) labelled "findings", (2) → (3)
> labelled "cited patch suggestions".
>
> **Elements — external actors:**
>
> - **Developer** (left, external): writes and reviews the spec.
> - **Team lead** (bottom-right, external, optional if space is tight):
>   watches telemetry.
>
> **Elements — external systems:**
>
> - **Anthropic API** (top): connected to Claude agent by an arrow labelled
>   "prompt + tool calls / patches".
> - **SigNoz observability stack** (bottom): connected to the approval
>   loop by an arrow labelled "traces + cost metrics + events".
>
> **Elements — data stores (cylinders):**
>
> - `openapi.yaml` — the developer's spec, left of the system, arrow in
>   labelled "spec".
> - `openapi.yaml` (mutated) + `.bak` — right of the system, arrow out
>   labelled "approved patches applied".
> - `gds-uplift-events.jsonl` — bottom-right, arrow out from the approval
>   loop labelled "audit trail".
>
> **Elements — additional outputs:**
>
> - **Findings report** (text/JSON) — right of the system, arrow out
>   labelled "report".
>
> **Visual style:**
>
> - Clean, professional, slide-friendly. Rounded rectangles, 12–16px
>   corner radius.
> - Muted palette: three colours maximum for containers, one accent for
>   internal components, dim grey for arrows.
> - White or #FAFAFA background. Dark #111 text. Sans-serif typography
>   (Inter, IBM Plex Sans, or similar).
> - 16:9 landscape, meant to fill a single slide comfortably.
>
> **Explicitly exclude:**
>
> - Decorative icons on components (no lightbulbs, robots, locks).
> - Marketing taglines, exclamation marks, or "AI-powered" copy.
> - "Made with AI" watermarks, corporate logos, brand marks.
> - More than five colours total.
> - Isometric or 3D perspective.
>
> **The single sentence the diagram must communicate without any
> narration:** "A developer's OpenAPI spec goes through eleven
> deterministic checks and a Claude agent that proposes cited fixes; the
> developer approves each patch, the tool writes an audited backup, and
> the team's observability stack sees every action."
>
> **Deliverable format:** high-resolution PNG at 1920×1080 minimum, plus
> the editable source (SVG or the tool's native format) so the label
> wording can be tweaked without regenerating.

---

## Iterating on the output

If the first pass isn't right, add one of these as a follow-up:

- "Make the system container visibly the largest element. It currently
  reads as one of many peer boxes."
- "The three internal components need to be visibly grouped inside the
  system container — a subtle background shade or a shared inner border
  would work."
- "Move the Anthropic API and SigNoz containers further from the tool so
  the primary developer → tool → outputs flow reads uninterrupted."
- "The arrows are too thick. Thin them to match the box borders."
- "Every arrow needs a label. Two are currently unlabelled — the one from
  {source} to {destination}, and {other one}."

## Success criteria (share with the designer for a self-check)

A stakeholder who has never seen the tool should be able to answer these
three questions from the diagram alone:

1. Who uses this tool? (answer: a developer)
2. What are the three things happening inside it? (answer: deterministic
   checks, AI patch proposals, human approval loop)
3. What comes out of it? (answer: a report, a patched spec, telemetry)

If any of those need narration to answer, the diagram needs another pass.
