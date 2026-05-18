
# USEMO Rubric Schema — Specification

## 1. Overview

This schema represents math olympiad grading rubrics in a form that can be authored from source rubric prose, validated for structural integrity, and used by a grading model (LLM or human) to produce judgments that are auditable, debate-able, and machine-checkable.

The schema has two artifacts:

- **Rubric**: a tree describing how a problem is scored. Authored once per problem.
- **Judgment**: a tree mirroring the rubric, recording a grader's verdict on a specific contestant paper.

A rubric and a judgment together produce a final score for a paper, computed structurally from the judgment tree.

### Design principles

The schema reflects the following commitments, in priority order:

1. **Faithfulness to source rubrics over schema cleverness.** When a source rubric says "both required; one alone earns 0," encode the structure (a parent with `satisfied_when: "all"`) rather than a notes field. Compound questions in `description` fields are a hallucination risk; sharp atomic yes/no questions are not.

2. **Auditable scoring.** Every score decomposes into a walk over the judgment tree with each node's contribution traceable. Two judgments over the same rubric are diffable for debate.

3. **Token efficiency in the grading turn, not the rubric turn.** Longer rubric JSON is acceptable if it makes the grader's job easier. The grader emits one judgment tree in a single pass, with stable IDs across rubric and judgment. When in doubt, err towards including information in a problem's grading JSON.

4. **Single-pass generation with deliberate context bleed.** The grader sees the full rubric and the full paper and produces one coherent judgment tree. No two-pass routing; routing decisions are encoded structurally in the judgment output.

5. **Validators over conventions.** Constraints are enforced by a validator, not by rubric authors remembering conventions. New constraints encode the intent and rely on the validator.

6. **Skepticism toward expressiveness for its own sake.** Predicates over arbitrary node states or computed scores tend to become unauditable. The schema has only two combinators and a small set of `satisfied_when` predicates.

7. **Honest modeling of what rubrics actually say.** When a source rubric says "5 points if A, B, C, D," the schema encodes this as `points: 5` with `satisfied_when: "all"` over [A, B, C, D] — not as a fabricated `sum` of invented per-claim weights.

---

## 2. Rubric Schema

### 2.1 Top-level rubric document

```json
{
  "rubric_version": "<author's version of this specific rubric>",
  "id": "<problem identifier>",
  "description": "<problem statement summary>",
  "points": <number | range>,
  "combinator": "sum" | "one_of",
  "guidelines": [<string>, ...],
  "children": [<Node>, ...]
}
```

The root behaves as a node (see §2.2). Its `points` must equal the problem's maximum possible score (typically 7).

### 2.2 Node

Every node has the shape:

```json
{
  "id": "<unique within tree, dot-path conventional>",
  "description": "<short atomic statement of what this node represents>",
  "points": <number | range>,
  "guidelines": [<string>, ...],         // optional
  "selection_signal": "<string>",        // required iff parent is one_of

  // exactly one of the following two fields, OR neither (leaf):
  "combinator": "sum" | "one_of",
  "satisfied_when": "all" | "any" | { "count_at_least": <int> },

  "children": [<Node>, ...]              // required iff combinator or satisfied_when present
}
```

A node falls into one of three shapes, determined by which fields are set:

#### Shape A: Leaf

- No `children` (or empty array).
- No `combinator`.
- No `satisfied_when`.
- The grader judges this binary: satisfied or not.
- Contribution: `points.default` if satisfied (or `points_awarded` if `points` is a range), else 0.

#### Shape B: Atomic-with-satisfaction

- Has `satisfied_when` and `children`.
- The node is satisfied iff its satisfaction condition over children's satisfaction states evaluates true.
- Children under such a node must NOT have their own `points` field (they are pure conditions, not scoring criteria).
- Contribution: `points.default` if satisfied (or `points_awarded` if range), else 0.

Satisfaction conditions:
- `"all"`: every child must be satisfied.
- `"any"`: at least one child must be satisfied.
- `{"count_at_least": k}`: at least `k` children must be satisfied.

#### Shape C: Composing

- Has `combinator` and `children`.
- The node's score is computed from children's scores:
  - `"sum"`: score is the sum of children's scores.
  - `"one_of"`: exactly one child is selected by the grader; score is that child's score.
- For `one_of`, every child must have a `selection_signal`.

### 2.3 Points

A node's `points` field is either a non-negative integer or a **range**:

```json
{
  "min": <int>,
  "max": <int>,
  "default": <int>,
  "scale": [
    { "value": <int>, "criterion": "<string>" },
    ...
  ]
}
```

Constraints:
- `min ≤ default ≤ max`, all non-negative integers.
- `scale` is non-empty.
- Every `value` in `scale` is in `[min, max]`.
- `scale` includes entries for both `min` and `max` (endpoints anchored).
- Values in `scale` should be distinct.
- Only values present in `scale` are awardable. Intermediate values not in `scale` are not separately awardable.

A range is used when the source rubric explicitly grants the grader discretion over a small set of award values within a single regime ("5–6 points for any tiny slip"). The `scale` makes the discrimination explicit: each award value is paired with a criterion telling the grader what kind of solution earns it.

When the source rubric does not give explicit within-regime latitude, use a fixed integer.

### 2.4 Selection signal

Every child of a `one_of` parent must carry a `selection_signal`: a string telling the grader when this regime applies. Selection signals partition the space of solutions; the grader picks the regime whose signal best matches the contestant's paper.

A `one_of` parent's children should jointly cover the space of possible papers. In particular, top-level `one_of` rubrics should typically include an explicit `no-progress` regime at 0 points, with selection signal "none of the above applies."

### 2.5 Guidelines

`guidelines` is an optional array of grader-facing strings. It is the home for content that is neither structural scoring nor a binary criterion. Examples:

- "0 points for stating the answer alone."
- "No deduction for small configuration issues or typos."
- "Most solutions are worth 0 or 7."
- "When ambiguous, prefer X over Y."
- Historical disagreement notes.

Guidelines should be ordered with framing/distributional content first (it shapes the grader's read of everything below), followed by anti-credit notes, then specific scoring guidance.

Guidelines must not be used to encode scoring structure that should live in the tree. If a guideline says "deduct 1 point if X," the rubric is hiding a regime; restructure it into a regime sibling.

### 2.6 What is NOT in the schema

The following were considered and rejected:

- **Deductions / `applies_if` predicates.** All deduction patterns encountered in olympiad rubrics dissolve into either nested regime alternatives (under `one_of`) or pure grader guidance (in `guidelines`).
- **`max` combinator.** Replaced by `one_of`, which records the regime selection explicitly. Every use of `max` was routing in disguise.
- **`bonus_if`, `exclusive_with`, cross-references between nodes.** Prefer duplication of conditions across regimes (with distinct IDs) over cross-references.
- **Predicate languages over computed score or other node states.** All cases dissolve into structural choices.
- **A third combinator for parallel scoring.** No real rubric needed it.

---

## 3. Validator Rules (Rubric)

A rubric is valid iff all of the following hold.

### Structural

2. **Root.** Root has `id`, `description`, `points`, and either `combinator` or `satisfied_when`.
3. **ID uniqueness.** Every node's `id` is unique within the tree.
4. **ID hierarchy convention.** Each child's `id` begins with its parent's `id` followed by `.` and a local segment. (Convention; soft check.)
5. **Shape exclusivity.** Each node has exactly one of: `combinator` set, `satisfied_when` set, or neither (leaf).
6. **Children presence.** A node with `combinator` or `satisfied_when` has a non-empty `children` array. A leaf has no `children` (or empty).

### Combinator-specific

7. **Selection signals.** Every child of a `one_of` parent has a non-empty `selection_signal`.
8. **No points under satisfied_when.** Children of an atomic-with-satisfaction (`satisfied_when`) parent must not have a `points` field.

### Arithmetic

9. **Sum arithmetic.** For a `sum` parent: `parent.points.default` equals the sum of `children[i].points.default` for all children.
10. **One-of upper bound.** For a `one_of` parent: `parent.points.default ≥ max(children[i].points.default)` for all children. (Equality is typical; strict greater-than is allowed if the parent contributes additional points beyond any child's regime.)

### Points

11. **Range integrity.** If `points` is a range:
    - `min`, `max`, `default` are non-negative integers.
    - `min ≤ default ≤ max`.
    - `scale` is non-empty.
    - Every `value` in `scale` is in `[min, max]`.
    - `min` and `max` both appear as values in `scale`.
    - `criterion` strings in `scale` are non-empty.

### Soft checks (warnings, not errors)

12. **No-progress regime.** Top-level `one_of` rubrics should include a child with `selection_signal` covering "none of the above" cases at 0 points.
13. **Distinct scale values.** Values in a range's `scale` should be distinct (duplicates indicate authoring error).
14. **Selection signal coverage.** A `one_of` parent's selection signals should jointly cover the space of plausible solutions.

---

## 4. Judgment Schema

### 4.1 Judgment node

A judgment tree mirrors the rubric tree's structure (modulo `one_of` collapsing to its selected child).

```json
{
  "id": "<matches rubric node id>",
  "reasoning": "<grader's reasoning for this node>",

  // for one_of rubric nodes:
  "selected": "<id of the chosen child>",

  // for leaves and atomic-with-satisfaction:
  "satisfied": <boolean>,

  // for nodes with range points (when satisfied or selected):
  "points_awarded": <int>,

  "children": [<JudgmentNode>, ...]
}
```

### 4.2 What each rubric shape requires in judgment

#### Leaf (rubric)

```json
{
  "id": "<matches>",
  "reasoning": "<why satisfied or not>",
  "satisfied": <bool>
  // include "points_awarded" if rubric points is a range and satisfied is true
}
```

No `children`.

#### Atomic-with-satisfaction (rubric)

```json
{
  "id": "<matches>",
  "reasoning": "<why the satisfaction condition does/doesn't hold>",
  "satisfied": <bool>,
  "children": [<judgment for each rubric child>, ...]
  // include "points_awarded" if rubric points is a range and satisfied is true
}
```

The `satisfied` field must be consistent with applying the rubric's satisfaction condition to children's `satisfied` values. The validator checks this.

#### Sum (rubric)

```json
{
  "id": "<matches>",
  "reasoning": "<optional summary of subscore>",
  "children": [<judgment for each rubric child>, ...]
}
```

No `selected`, no `satisfied`. Score is computed as the sum of children's scores.

#### One_of (rubric)

```json
{
  "id": "<matches>",
  "reasoning": "<why this regime was selected>",
  "selected": "<id of the selected child>",
  "children": [<single judgment for the selected child only>]
}
```

Exactly one child judgment, whose `id` equals `selected`. The other rubric children are not represented in the judgment tree.

### 4.3 Score computation

The score of a judgment tree is the contribution of its root:

- A satisfied leaf contributes `points.default`, or `points_awarded` if the rubric used a range.
- An unsatisfied leaf contributes 0.
- An atomic-with-satisfaction node contributes `points.default` (or `points_awarded`) if `satisfied`, else 0.
- A `sum` node contributes the sum of its children's contributions.
- A `one_of` node contributes its single judgment child's contribution.

The final score equals the root's contribution.

---

## 5. Validator Rules (Judgment)

A judgment is valid against a rubric iff:

### Structural

1. **Schema mirror.** Every judgment node has an `id` matching a rubric node `id`. The judgment tree's structure matches the rubric tree, modulo `one_of` collapsing to its selected child.
2. **Reasoning presence.** Every judgment node has a non-empty `reasoning`.

### Shape-specific

3. **Leaf judgments.** Have `satisfied`, no `children`, no `selected`.
4. **Sum judgments.** Have `children` matching all rubric children. No `satisfied`, no `selected`.
5. **Satisfied_when judgments.** Have `satisfied`, `children` matching all rubric children. The `satisfied` value must be consistent with applying the satisfaction condition to children's `satisfied` values.
6. **One_of judgments.** Have `selected` naming an actual rubric child. `children` contains exactly one judgment, whose `id` equals `selected`.

### Range-related

7. **Points awarded presence.** When the rubric node uses a range and the node contributes points (leaf is satisfied, or atomic-with-satisfaction is satisfied, or one_of's selected child uses a range), `points_awarded` must be present.
8. **Points awarded value.** `points_awarded` must equal one of the values in the rubric's `scale`.
9. **No spurious points awarded.** When the rubric uses a fixed integer, `points_awarded` must not be present.

### Soft checks

10. **Selection signal grounding.** For `one_of` judgments, the `reasoning` should make contact with the selected child's `selection_signal`. (Hard to validate mechanically; flag for human or debater review.)
11. **Coverage of "no-progress" cases.** If a paper has no real progress and the rubric has a `no-progress` regime, the judgment should select it rather than another low-scoring regime.

---

## 6. Authoring Patterns

These are recurring patterns observed in source olympiad rubrics, with their canonical encoding. A translation pipeline (free-text rubric → rubric JSON) should be primed to recognize these.

### 6.1 Completeness as its own regime

When a source rubric says "complete solution worth N points" alongside additive partial-credit items that don't sum to N, "complete" is its own atomic regime, not a fabricated sum.

Encoding: `one_of` over [`complete` (atomic, `satisfied_when: "all"`, points = N), `partial-additive` (sum, points capped at the highest reachable partial total), `no-progress` (0)].

Source rubric signals: a "perfect solution worth N" line accompanying a partial-credit list whose item points don't sum to N.

### 6.2 "Additive deductions" that are mutually exclusive regime shifts

Source rubrics often phrase scoring rules as "−N for X" or "−N for Y." On close reading, most such deductions are mutually exclusive (a paper triggers at most one) and convert cleanly to nested `one_of` regime alternatives.

Encoding: each deduction becomes a sibling regime under a `one_of`, with `selection_signal` describing what kind of paper falls into it.

Source rubric signals: "−N for X" language. Translation must check whether deductions stack in practice; if they do, this pattern doesn't apply (but no such case has been observed in olympiad rubrics).

### 6.3 "Non-additive with anything" as a top-level one_of marker

Some rubrics list a partial-credit item with explicit "not additive with anything" or "non-additive with the rest" language. This is a top-level `one_of` regime, not an additive contributor.

Source rubric signals: "non-additive," "not additive with anything," "(not additive)."

### 6.4 Grader-discretion ranges

When the source rubric grants the grader discretion over a small set of award values within a single regime ("5–6 points for any tiny slip"), encode as a range with explicit `scale`.

Source rubric signals: "X–Y points for [condition]" or similar.

The `scale` field forces the rubric author to articulate the within-range distinction even when the source didn't.

### 6.5 `satisfied_when: "any"` for "either X or Y" with a single point value

When a rubric awards a fixed value if any of several alternative conditions hold, use `satisfied_when: "any"` over the alternatives rather than encoding each as a separate regime.

Source rubric signals: "for either establishing X or proving Y," with a single point value.

### 6.6 Conditional-on-X regimes

When a rubric awards partial credit for solutions that quote a step rather than prove it ("conditional on the corollary," "assuming a well-known result"), encode this as a regime, not an `applies_if` predicate.

Source rubric signals: "conditioned on X," "assuming Y without proof," "if the contestant uses Z without justification."

### 6.7 Pure one_of ladders

Some rubrics are entirely `one_of` ladders with no additive component, explicitly stating "none of these items are additive."

Source rubric signals: "none of these items are additive," a list of items at progressively higher point values that describe progressively more complete solutions.

### 6.8 Sub-regimes inside listed items

When a partial-credit item has a footnote like "this item is only worth 1 point if the solution does not at least claim X," the item is itself a `one_of` over sub-regimes (or splits into sibling regimes at the parent level).

Source rubric signals: "only worth N if not Y," sub-conditions attached to a single listed item.

### 6.9 Distributional guidance from source rubrics

Sentences describing the expected score distribution or the rubric author's intent ("most solutions are 0 or 7," "this is a hard problem and partial credit is rare") are not structural but are real grader-facing content. Place them in top-level `guidelines`, with framing content first, before structural guidelines.

Source rubric signals: leading prose talking about scores in the abstract ("most are X or Y," "expect Z," "this problem is hard") rather than describing what to award for what.

### 6.10 "0 points for X" content

When a source rubric explicitly enumerates things that earn 0 points, this is grader guidance — not a scoring criterion that should be a `points: 0` leaf. Place these statements in `guidelines`.

Source rubric signals: "0 points for [observation/statement]," "no points for [trivial work]."

---

## 7. Grading Workflow

The intended pipeline:

1. **Authoring.** A rubric is authored once per problem, encoded as a rubric document, validated.
2. **Translation (optional).** A free-text source rubric (e.g., from a contest report) is translated to rubric JSON by an LLM with a translation prompt seeded with the patterns in §6, then validated.
3. **Grading.** A grading LLM receives the rubric, the problem statement, the reference solution(s), and the contestant's paper. It emits a judgment tree in a single pass.
4. **Validation.** The judgment is validated against the rubric (§5).
5. **Score computation.** The final score is computed structurally from the judgment tree (§4.3).
6. **Debate (optional).** Two judgment trees over the same rubric are diffable. Disagreements localize to specific nodes — `selected` for `one_of`, `satisfied` for atomic, `points_awarded` for ranges. Each disagreement carries grader reasoning that can be debated independently.

The schema supports both single-pass (whole-paper) grading and per-criterion grading (one judgment node at a time). Single-pass is the primary mode; per-criterion is a baseline for evaluation.

---

## 8. Rubric Versioning

- `rubric_version`: the rubric author's version of a specific problem's rubric (e.g., "1.0", "1.1"). Allows iteration on a specific rubric without confusion.

## Appendix A — Design decisions

This appendix records the reasoning behind the schema's main shape choices. It exists to support reviewers and future maintainers in understanding *why* the schema is the way it is, not just what it is.

### A.1 Why `one_of` instead of `max`

Earlier iterations of this schema had a `max` combinator: a parent's score was the maximum of its children's scores, with each child scored independently and the highest taken. This schema replaces `max` with `one_of`, where a parent's score is the score of a single child explicitly selected by the grader.

The substantive arguments for the change:

**Routing is what graders actually do.** Every observed use of `max` in encoded olympiad rubrics turned out to be regime classification — a paper is on solution path A or path B or partial credit, not all three at once. Graders read a paper, classify it, then score within the classification. `max`'s "score every branch and take the highest" framing was a fiction layered over what was already a one-of-N decision. Replacing `max` with `one_of` makes the schema match grader behavior rather than papering over it.

**Commitment structure for single-pass generation.** Under `max`, a model reaching a `max`-parent has to score every branch, then the score-computation step takes the maximum. The model's reasoning traverses all branches in parallel, with no anchoring commitment. Under `one_of`, the model writes `selected: "<child-id>"` and from that point on its reasoning is about the chosen branch alone. There is a commitment point in the output stream, after which subsequent reasoning is constrained to the chosen regime.

This matters because the user's stated priority is single-pass generation with deliberate context bleed — the bleed should be *within a regime*, not *across regimes*. `max` violates this: the model is forced to reason about every branch, and that reasoning can contaminate whichever branch is ultimately chosen ("well, I already considered partial-additive, so I'll be slightly generous on the complete regime to match"). `one_of` enforces the right scope of context bleed by forcing commitment.

**Auditability and debate.** The auditability advantage of `one_of` is not just that the routing decision is recorded as a field. The deeper point: under `one_of`, a grader's reasoning is *about one regime*, with `selection_reasoning` separate from the within-regime criterion judgments. A debater attacking a `one_of` judgment can target either the regime selection or the within-regime grading; the attack surfaces are clean and separable. Under `max`, the grader's reasoning runs in parallel across branches, and the implicit comparison is what determines the score — but the comparison is implicit, with nothing to point at. Debate over a `max` judgment requires engaging with multiple reasoning chains and an implicit max-pick, which is harder to do well.

**Downstream simplification.** `one_of`'s "pick one regime" semantics is what makes deductions disappear. Under `max`, deduction-style scoring rules ("−1 for wrong answer if otherwise 7") have nowhere natural to live in the tree — they need to be `applies_if` predicates outside the structure. Under `one_of`, deductions dissolve into sibling regimes (a 6pt regime alongside the 7pt regime, with selection signal "argument complete but answer wrong"). Replacing `max` with `one_of` was upstream of removing deductions and `applies_if` from the schema entirely.

The cost of the change: `one_of` is more demanding of the grader. They must commit to a regime even when the case is fuzzy, where `max` would have let them score multiple branches and let arithmetic decide. The schema treats this as a feature: forcing the commitment surfaces decisions that were always present, just hidden inside `max`'s comparison step. Where the grader is genuinely unsure, the right response is `selection_reasoning` that articulates the uncertainty and lets a debater attack — not silent reliance on `max` to paper over indecision.

The argument from honest modeling: rubrics where the source author explicitly says "score the highest applicable" are rare to nonexistent in the encoded corpus. The pattern that does occur is "the contestant's solution lives in one of these regimes." `one_of` matches this; `max` invented a parallel-scoring fiction.

### A.2 Why no deductions

Earlier iterations had a separate concept of deductions: rules outside the rubric tree that subtracted points based on `applies_if` predicates over computed score or named criterion satisfaction. This schema removes deductions entirely; all observed deduction patterns dissolve into either nested regime alternatives (under `one_of`) or pure grader guidance (in `guidelines`).

The argument is empirical: across the rubrics encoded in development, every "deduction" in source rubric prose fell into one of three categories:

1. **Mutually exclusive regime shifts in disguise.** "−1 for wrong final answer if otherwise 7" reads as a deduction but is actually a regime: "argument complete, answer wrong" at 6pt, sibling to the 7pt complete regime. The conditional "if otherwise 7" is what makes it a regime — it identifies a specific shape of solution, not a stackable adjustment.
2. **Within-regime grader latitude.** "−1 for sign errors that don't affect the solution" is grader guidance about how to interpret an essentially-complete solution with a small fault — it lives in `guidelines`, not as a scoring rule.
3. **Pure grader guidance.** "No deduction for typos or directed-angle issues" is anti-anti-credit content for `guidelines`.

In none of these cases did a deduction need to live as a stackable, score-modifying rule independent of regime structure. The "global deductions like '−1 for wrong final answer when score ≥ 6'" pattern that earlier versions worried about turned out to dissolve in every concrete case.

The removal benefits: no `applies_if` predicate language, no validator complexity for predicate evaluation, no debate-time confusion about whether a deduction fires before or after another adjustment. The schema's score-computation rules are purely structural: walk the tree, apply combinators, sum or pick.

The risk to monitor: if a future olympiad rubric introduces genuinely stackable deductions that combinatorially co-occur on a single paper (e.g., "−1 for X and additionally −1 for Y, where both are independently triggered"), nesting those into 2^k regimes becomes unwieldy. No such case has been observed in the development corpus. If it appears, the right response is to revisit deductions as a schema feature rather than encode the 2^k regimes — but only at that point, not preemptively.

### A.3 Why ranges over regime-splitting

When the source rubric grants the grader discretion within a regime ("5–6 points for any tiny slip"), The schema encodes this as a `points` range with a required `scale` array. An alternative would be to split the range into multiple regimes (5pt and 6pt as distinct `one_of` siblings).

The argument for ranges:

**The rubric author's framing matters.** When a source rubric says "5–6 points for X," the author is treating this as a single regime with internal latitude. Splitting into two regimes would invent a binary distinction the author declined to make. Ranges preserve the source's framing: one regime, internal scale.

**The `scale` array forces articulation anyway.** The objection to a range — "but how does the grader pick within the range?" — is addressed by requiring `scale`, which pairs each awardable value with a discriminating criterion. The grader's choice is structurally surfaced, debate-attackable, and validator-checkable, just like a regime selection. The information content of `range with scale` is essentially the same as that of `one_of with two regimes`; the difference is in framing and in whether the rubric author's own grouping is preserved.

**Endpoint-anchoring keeps it honest.** Validator rule 11 requires that `min` and `max` both appear in `scale`. This prevents a rubric author from declaring a wide range with a narrow effective scale (e.g., `min: 4, max: 7, scale: [{value: 7, ...}, {value: 6, ...}]`). The full range must be articulated; otherwise the rubric author should have just used a fixed value.

The cost: ranges are a third points-encoding alongside fixed integers and the rejected predicate-language alternatives. They add a small validator-rule load. The benefit (preserving rubric-author framing) is a stylistic rather than structural one. Worth monitoring whether the scale-articulation requirement adds enough discipline to justify the third encoding, or whether range cases should be normalized to multi-regime in practice.

### A.4 Why `selection_signal` lives on the regime, not the parent

A `one_of` parent's children carry `selection_signal`. The signal could alternatively have lived on the parent as a field describing how to discriminate among children — "here are the regimes, here's how to pick."

The choice to put it on the regime preserves the property that a regime can be moved or refactored without disrupting the parent. A regime's selection signal is a property of the regime itself ("this is when this kind of solution applies"), not a property of the comparison group. Lifting and merging regimes across `one_of`s requires no rewriting of selection logic.

It also matches `description`'s placement: every node has a `description` of itself; every `one_of` regime has a `selection_signal` for itself. Consistent with the schema's general preference for node-local properties over relationship-encoding fields.

### A.5 Why duplication over cross-references

When the same condition appears in multiple regimes (e.g., "claim B is required for both partial-credit branch X and partial-credit branch Y"), The schema prefers duplicating the criterion under both regimes (with distinct IDs) over introducing cross-references between nodes.

The argument:

**Cross-references become unauditable fast.** A criterion referenced from two places has to be evaluated once. Which place's reasoning is the canonical one? If the two places have different surrounding context (different parent regime, different sibling criteria), the criterion's evaluation may need to differ — but a cross-reference forces a single evaluation. Duplication preserves contextual independence.

**Tree-walks stay linear.** The grading and validation algorithms are tree walks: visit each node once, recurse into children. Cross-references break this — they require a graph traversal with cycle detection or memoization. The marginal expressive gain isn't worth the algorithmic complexity.

**Debate is cleaner.** A duplicated criterion can be debated independently in each context. A cross-referenced criterion has a single judgment that both contexts depend on; debate at that judgment cascades to multiple regimes, which is harder to reason about.

The cost: rubric authors write the same criterion text twice (or more) with different IDs. This is a real authoring burden, but it's bounded by the typical olympiad rubric size (≤ 10 distinct criteria per problem) and is paid once at authoring time, not on every grading.

### A.6 Why the schema has no `count_at_least: k` use yet, but supports it

The `satisfied_when` field accepts `{"count_at_least": k}` as an option, but no rubric in the development corpus has needed it. The two values that have been used are `"all"` (most common) and `"any"` (occasional, e.g., P5-2025's "either bound" criteria).

The choice to include `count_at_least: k` in the schema despite no current use:

**It's a natural generalization.** `"all"` is `count_at_least: n` (where n is the number of children); `"any"` is `count_at_least: 1`. Including the parameterized form makes the design space explicit without committing to specific arities.

**Some olympiad rubrics could plausibly use it.** "At least 3 of these 5 cases must be addressed" patterns appear in problems with multiple equally-valued sub-cases (e.g., "the construction works for at least three of the residue classes"). None have appeared in encoding so far, but the cost of supporting it is one validator rule.

**Removing it later is harder than including it now.** If the schema ships without `count_at_least: k` and a rubric needs it, the schema has to be extended — and the migration of older rubrics through the version bump is annoying. Including it preemptively avoids this.

The cost: one additional case in the satisfaction-condition validator and judgment-consistency check. Small.

### A.7 What the schema does not solve

Worth being explicit about what the schema does *not* address, so future iterations don't reinvent these concerns:

**Translation from free text.** The schema is a target representation, not a translation pipeline. The translation prompt (separate document) is where the work of going from prose rubrics to rubric JSON happens. Schema changes that make translation easier are valuable, but the schema is not designed *for* translation specifically.

**Grading prompt design.** Likewise, the grading prompt is separate. The schema specifies what a judgment looks like; how a model is induced to produce that judgment is a prompting concern.

**Inter-grader agreement metrics.** Two judgments over the same rubric are diffable, but the schema doesn't specify how to weight or aggregate disagreements. That's a debate-protocol concern, not a schema concern.

**Authoring tooling.** No schema-aware editor, syntax-highlight, or interactive validator is specified. These are valuable but downstream of the schema being stable.

## Appendix B - Examples

### Appendix B.1 - 2025 USEMO P2 



Problem prompt: 

Let ABC be a fixed triangle with circumcircle ω. Consider P a variable point inside
ABC. Ray BP meets side AC at Y while ray CP meets side AB at X. Let Q be
the second intersection of ω and the circumcircle of triangle AXY . Let K be the
second intersection of ray AP and ω.
Prove that as P varies, the circumcircles of triangle QP K all have a common
radical center.

Corresponding rubric: 

{
  "rubric_version": "1.0",
  "id": "usemo-2025-p2",
  "description": "Show that as P varies inside fixed triangle ABC, the circumcircles of triangle QPK have a common radical center.",
  "points": 7,
  "combinator": "sum",
  "guidelines": [
    "The intended fixed point is M, the midpoint of BC.",
    "The +1 for naming M as the fixed point is additive with everything else.",
    "No deductions for typographical issues or configuration issues that can be resolved by directed angles.",
    "If a solution is correct contingent on an unproven claim, route to the 0+ scheme unless the claim is a well-known result (e.g., the existence of the Newton-Gauss line, spiral similarities occurring in pairs, Zack's lemma) or a minor omission. Stating moving-points / gliding-principle / 4QXY ~ 4QBC / Newton-Gauss line / Zack's lemma without significant progress earns 0pt under 0+."
  ],
  "children": [
    {
      "id": "fixed-point-claim",
      "description": "States that the fixed point (the common radical center) is M, the midpoint of BC.",
      "points": 1
    },
    {
      "id": "main-scheme",
      "description": "The main solution work, scored under one of two schemes: 7- (essentially correct) or 0+ (incomplete partial credit).",
      "points": 6,
      "combinator": "one_of",
      "children": [
        {
          "id": "main-scheme.complete",
          "selection_signal": "Solution gives a complete and correct synthetic argument that M lies on the radical axis of all (QPK), with no substantive gaps and no uncited well-known facts that have not been proven.",
          "points": 6,
          "satisfied_when": "all",
          "children": [
            { "id": "main-scheme.complete.argument", "description": "Complete and correct synthetic proof that M is the common radical center." }
          ]
        },
        {
          "id": "main-scheme.well-known-fact-uncited",
          "selection_signal": "Solution is essentially correct in structure and reaches the conclusion, but assumes a named well-known result without proof or proper citation. Apply specifically when: (a) the assumption is unambiguously an instance of a recognized lemma (Newton-Gauss line, spiral similarity occurring in pairs, Zack's lemma in moving points), and (b) no further mathematical work needs to be done beyond invoking the lemma. If the use is unclear or the lemma is misapplied, route to 0+ instead.",
          "points": 5,
          "satisfied_when": "all",
          "children": [
            { "id": "main-scheme.well-known-fact-uncited.essentially-correct", "description": "Argument is essentially correct, depends on a named well-known result that the contestant invokes without proof or citation." }
          ]
        },
        {
          "id": "main-scheme.minor-fixable-detail",
          "selection_signal": "Solution is essentially correct but missing a minor detail the contestant could have easily repaired. Examples per source: a singular missing degenerate moving-points case in an otherwise correct list, an obvious-from-context equality omitted from an angle chase. Use only when no other regime better describes the work.",
          "points": 4,
          "satisfied_when": "all",
          "children": [
            { "id": "main-scheme.minor-fixable-detail.essentially-correct", "description": "Argument is essentially correct modulo a minor easily-reparable detail." }
          ]
        },
        {
          "id": "main-scheme.zero-plus",
          "selection_signal": "Solution does not reach an essentially-correct argument: incomplete computational approaches, claims without proof, or fragments without a working radical-axis argument. Score under the 0+ scheme.",
          "points": 2,
          "combinator": "one_of",
          "guidelines": [
            "Capped at 2pt under main-scheme; the +1 fixed-point claim sits above as a sibling.",
            "Stating named theorems or facts without significant progress earns 0pt here.",
            "Incomplete algebraic / coordinate / moving-points solutions are 0pt by default unless they include an independent synthetic claim with proof.",
            "The four 2pt named claims are non-additive to each other; the grader picks at most one."
          ],
          "children": [
            {
              "id": "main-scheme.zero-plus.qlmk-concyclic",
              "selection_signal": "Solution proves that Q, L, M, K are concyclic (where L is the midpoint of AP and K is the second intersection of ray AP with ω).",
              "points": 2,
              "satisfied_when": "all",
              "children": [
                { "id": "main-scheme.zero-plus.qlmk-concyclic.proof", "description": "Valid proof of the QLMK concyclicity." }
              ]
            },
            {
              "id": "main-scheme.zero-plus.p-on-b1c1",
              "selection_signal": "Solution proves that P lies on line B₁C₁ (where B₁, C₁ are the points on AB, AC such that the relevant circumcircles are tangent to AC, AB respectively).",
              "points": 2,
              "satisfied_when": "all",
              "children": [
                { "id": "main-scheme.zero-plus.p-on-b1c1.proof", "description": "Valid proof that P lies on B₁C₁." }
              ]
            },
            {
              "id": "main-scheme.zero-plus.z-on-b1c1-and-gamma",
              "selection_signal": "Solution proves that Z (the second intersection of the circumcircles of BB₁Q and CC₁Q) lies on both line B₁C₁ and circle Γ.",
              "points": 2,
              "satisfied_when": "all",
              "children": [
                { "id": "main-scheme.zero-plus.z-on-b1c1-and-gamma.proof", "description": "Valid proof that Z lies on both B₁C₁ and Γ." }
              ]
            },
            {
              "id": "main-scheme.zero-plus.alternate-comparable",
              "selection_signal": "Solution proves a synthetic claim along an alternate solution path of comparable value to the named claims above. Highlight the claim explicitly for grader consistency.",
              "points": 2,
              "satisfied_when": "all",
              "children": [
                { "id": "main-scheme.zero-plus.alternate-comparable.proof", "description": "Valid proof of a comparable-value synthetic claim." }
              ]
            },
            {
              "id": "main-scheme.zero-plus.no-substantial-progress",
              "selection_signal": "Solution is in the 0+ scheme and does not prove any of the named 2pt claims or a comparable-value alternate.",
              "points": 0,
              "satisfied_when": "all",
              "children": []
            }
          ]
        },
        {
          "id": "main-scheme.no-progress",
          "selection_signal": "Solution shows no substantial progress: blank, off-topic, or only restates the problem.",
          "points": 0,
          "satisfied_when": "all",
          "children": []
        }
      ]
    }
  ]
}
