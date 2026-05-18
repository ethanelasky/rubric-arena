# USEMO Rubric Translation Prompt

You are given a free-text source rubric for a math olympiad problem (typically from a contest report) and asked to translate it into the USEMO Rubric Schema (a structured JSON form). Your output is a rubric JSON document that faithfully reflects the source.

## Inputs

You will receive:

1. **The problem statement.**
2. **One or more reference solutions.** The "official" solution(s) the rubric was written against.
3. **The source rubric.** Free-text grader instructions: usually a list of items with point values, possibly with deductions, guidelines, and prose framing.

## Output

Two things, in this order:

1. **A structural commitment in prose** (3–8 paragraphs, see §4 of this prompt).
2. **The rubric JSON document**, consistent with the commitment.

No preamble, no postamble.

## §1 — Schema 

A rubric is a tree. Every node:
```json
{ "id": "<unique within tree, dot-path style>", "description": "<short, atomic, single yes/no question — never compound>", "points": <non-negative int OR range, see below>, "guidelines": [<string>, ...], // optional grader-facing prose "selection_signal": "<string>", // required iff parent is one_of // exactly one of the following two, OR neither (leaf): "combinator": "sum" | "one_of", "satisfied_when": "all" | "any" | { "count_at_least": <int> }, "children": [<Node>, ...] // required iff combinator or satisfied_when }
```

### Combinators

- **`sum`**: children are additive. Parent's `points` = sum of children's `points`.
- **`one_of`**: children are mutually exclusive regimes. Grader selects exactly one. Parent's `points` ≥ max of children's `points` (usually equal). Every child needs a `selection_signal`.

### `satisfied_when` (atomic-credit-on-conditions)

For nodes whose score is binary, gated by a condition over children:

- **`"all"`**: every child satisfied.
- **`"any"`**: at least one child satisfied.
- **`{"count_at_least": k}`**: at least k children satisfied. `k` must be a positive integer.

Children of `satisfied_when` nodes must NOT have their own `points` (they are conditions, not scoring criteria). The parent contributes its `points` if satisfied, 0 otherwise.

### Points: fixed or range

Either a non-negative integer, or a range:

```json
{
  "min": 5, "max": 6, "default": 6,
  "scale": [
    { "value": 6, "criterion": "Slip is genuinely tiny: typo, single missing equality, ..." },
    { "value": 5, "criterion": "Slip is more substantial: missing degenerate case, ..." }
  ]
}
```

`scale` must include both `min` and `max` as values, and `default` must satisfy `min <= default <= max`. Only values in `scale` are awardable. Use a range only when the source rubric explicitly grants discretion within a regime ("5–6 points for any tiny slip"); the `scale` criteria must distinguish the values clearly enough that an LLM grader can pick.

### Guidelines

`guidelines` carries grader-facing prose that is NOT structural scoring:

- "0 points for stating the answer alone."
- "No deduction for typos or directed-angle issues."
- "Most solutions are worth 0 or 7."

Order with **distributional/framing content first** (it shapes the read of everything below), then anti-credit notes, then specific scoring guidance.

### Not in the schema

No deductions. No `applies_if` predicates. No `max` combinator. No `bonus_if`. No cross-references between nodes. If the source uses deduction language, restructure (Pattern 2 below).

## §2 — Translation patterns

Source olympiad rubrics recur in predictable shapes. Recognize these.

**Pattern 1: Completeness as its own regime.** If the source says "N points for a complete solution" alongside additive items that don't sum to N, "complete" is its own atomic regime — not a fabricated sum. Use `one_of` over [`complete` (atomic, `satisfied_when: "all"`, points = N), `partial-additive` (sum, capped at the highest reachable partial total), `no-progress` (0pt)].
*Signal:* items with point values like "0, 1, 1, 2, 7" where 0+1+1+2 ≠ 7, accompanied by "the four items together give a complete solution worth 7."

**Pattern 2: "Additive deductions" that are mutually exclusive regime shifts.** Source rubrics often say "−N for X" or "−N for Y." Most such deductions are mutually exclusive — a paper triggers at most one. Encode each as a sibling regime under a `one_of`, with `selection_signal` describing what kind of paper falls into it.
*Signal:* "−N points for X" / "deduct N if Y." Check whether the deductions can stack on a single paper. Almost always they can't, and the right encoding is sibling regimes.
*Example.* "−1 for wrong final answer (only on otherwise-7 solutions)" → sibling regime at 6pt next to the 7pt complete regime, with `selection_signal: "Argument is essentially complete but the final stated answer is wrong, missing, or incorrectly simplified."`

**Pattern 3: "Non-additive with anything."** When a partial-credit item has explicit "not additive with anything" or "non-additive" language, it's a top-level `one_of` regime, not part of an additive bundle.
*Signal:* "non-additive," "not additive with anything," "(not additive)."

**Pattern 4: Grader-discretion ranges.** When the source grants the grader discretion within a regime ("5–6 points for any tiny slip"), encode as a range with `scale`. The `scale` criteria force articulation of the within-range distinction even if the source didn't.
*Signal:* "X–Y points for [condition]."

**Pattern 5: `satisfied_when: "any"` for "either X or Y" with single point value.** When a rubric awards a fixed value if any of several alternatives hold, use `satisfied_when: "any"`. Don't split into multiple regimes if the source treats them as one item.
*Signal:* "for either establishing X or proving Y," "1 point for any of the following."

**Pattern 6: Conditional-on-X regimes.** When a rubric awards partial credit for solutions that quote a step rather than prove it ("conditional on the corollary"), encode as a regime, not an `applies_if` predicate.
*Signal:* "conditioned on X," "assuming Y without proof."

**Pattern 7: Pure `one_of` ladders.** Some rubrics are entirely `one_of` ladders with no additive component, explicitly stating "none of these items are additive."
*Signal:* "none of these items are additive," followed by progressively higher point values describing progressively more complete solutions.

**Pattern 8: Sub-regimes inside listed items.** When a partial-credit item has a footnote like "this item is only worth 1 point if the solution does not at least claim X," the item is a `one_of` over sub-regimes (or splits into sibling regimes at the parent level).
*Signal:* "only worth N if not Y," sub-conditions on a single item.

**Pattern 9: Distributional guidance.** Sentences describing expected score distribution or rubric-author framing ("most solutions are 0 or 7," "this is a hard problem and partial credit is rare") belong in top-level `guidelines`, ordered first.
*Signal:* leading prose about scores in the abstract rather than describing what to award.

**Pattern 10: "0 points for X" content.** Source statements of what earns 0 points are grader guidance, not `points: 0` leaves. Place in `guidelines`.
*Signal:* "0 points for [observation]," "no points for [trivial work]."

## §3 — Anti-patterns

Three failure modes to avoid. Each shows the source language, the wrong encoding, and what to do instead.

### Anti-pattern A: Fabricating arithmetic for completeness

**Source:** "(a) 1 point for proving X. (b) 1 point for proving Y. (c) 2 points for proving Z. (d) 0 points for the trivial observation. **The four items above, when combined, give a perfect solution worth 7.**"

**Wrong encoding:**
```json
{
  "id": "main", "combinator": "sum", "points": 7,
  "children": [
    { "id": "main.a", "points": 1, ... },
    { "id": "main.b", "points": 1, ... },
    { "id": "main.c", "points": 2, ... },
    { "id": "main.completeness-topup", "points": 3, "description": "Remaining points for full solution." }
  ]
}
```

This invents a 3-point "completeness top-up" that the source never claimed. The arithmetic is fictitious — the source rubric is conflating "items that together demonstrate completeness" with "items whose points sum to the completeness score." These are different.

**Right encoding (Pattern 1):**
```json
{
  "id": "main", "combinator": "one_of", "points": 7,
  "children": [
    {
      "id": "main.complete",
      "selection_signal": "Solution proves all of X, Y, Z and reaches the conclusion.",
      "points": 7, "satisfied_when": "all",
      "children": [ /* X, Y, Z as binary criteria */ ]
    },
    {
      "id": "main.partial",
      "selection_signal": "Solution earns one or more partial-credit items but is not complete.",
      "points": 4, "combinator": "sum",
      "children": [
        { "id": "main.partial.a", "points": 1, ... },
        { "id": "main.partial.b", "points": 1, ... },
        { "id": "main.partial.c", "points": 2, ... }
      ]
    },
    {
      "id": "main.no-progress",
      "description": "No-progress fallback regime.",
      "selection_signal": "None of the above applies.",
      "points": 0
    }
  ]
}
```

`complete` is its own atomic 7pt regime gated on actually proving the result. `partial` caps at 4pt. The fictitious 3-point gap between 4 and 7 reflects the genuine difference between "earned some partial items" and "proved the result completely."

### Anti-pattern B: Encoding deductions as `applies_if`

**Source:** "−1 point for wrong final answer (only for solutions that would otherwise score 7). −2 points for items (3) or (4) with wrong bound expressions."

**Wrong encoding:**
```json
{
  "deductions": [
    { "id": "wrong-answer", "applies_if": "score == 7", "delta": -1 },
    { "id": "wrong-expression", "applies_if": "items 3 or 4 satisfied", "delta": -2 }
  ]
}
```

The schema has no `applies_if` and no `deductions`. Inventing them sneaks in a predicate language that's hard to validate, hard to debate, and unnecessary.

**Right encoding (Pattern 2):** Each deduction becomes a sibling regime in a top-level `one_of`. The "−1 for wrong answer when otherwise 7" is the regime "Argument complete but answer wrong" at 6pt, sibling to the 7pt complete regime. The "−2 for wrong expression on item 4" is the regime "Item 4 mechanism correct but expression wrong" at 3pt, sibling to the 5pt "item 4 fully correct" regime. No predicates; just regimes with selection signals.

### Anti-pattern C: Compound descriptions

**Source:** "1 point for considering the spiral similarity AND claiming its center is the concurrency point."

**Wrong encoding:**
```json
{
  "id": "spiral-claim",
  "description": "Considers the spiral similarity AND claims its center is the concurrency point AND reasons about the angle structure correctly.",
  "points": 1
}
```

This packs three questions into one description. An LLM grader has to evaluate "is all of this true?" with no structural scaffolding, and the answer is fuzzy. Hallucination risk.

**Right encoding:** If the source rubric treats it as one item with one point value, the outer node is `satisfied_when: "all"` over atomic sub-criteria:

```json
{
  "id": "spiral-claim",
  "description": "The spiral-similarity-as-concurrency-center claim.",
  "points": 1,
  "satisfied_when": "all",
  "children": [
    { "id": "spiral-claim.identifies-similarity", "description": "Identifies the spiral similarity taking R₁...R₁₀₀ to B₁...B₁₀₀." },
    { "id": "spiral-claim.center-is-concurrency", "description": "Claims that the center of this spiral similarity is the concurrency point." }
  ]
}
```

Each sub-criterion is sharp, atomic, yes/no. The grader can check them independently. The outer node's score is 0 or 1, gated by the `"all"` condition. This preserves the source's atomicity (one item, one point) while making the criterion structurally sharp.

The same logic applies whenever a source-rubric item uses "AND" or lists multiple things to verify.

## §4 — Procedure

### Step 1: Read carefully

Read the problem, reference solutions, and source rubric. Identify the rubric's overall shape: primarily additive items, a ladder of mutually exclusive regimes, or a mix?

### Step 2: Scan for patterns

Walk through Patterns 1–10 in §2. Note which apply. Common combinations:
- A `one_of` of regimes, each containing `sum` of items or `satisfied_when: "all"` over conditions (most common — fits most USEMO rubrics).
- Pure `one_of` ladder (Pattern 7).
- `sum` at top level with `one_of` regimes inside one of the items (rarer).

### Step 3: Resolve ambiguities deliberately

Common ambiguities and how to resolve:
- "1 point for the answer" alongside fuller items: usually fuller items implicitly include the answer. The 1pt item is its own regime for answer-only papers, not additive.
- "Item X is only worth N if Y": Pattern 8 — sub-regimes.
- A list switching between additive and non-additive without flagging: look for "the following are additive" / "non-additive" headers.
- Source rubric language that sounds like a deduction but applies to only one specific case: Pattern 2.

### Step 4: Write the structural commitment in prose

Before any JSON, write 3–8 paragraphs covering:
- Top-level shape and regimes (or additive items).
- Per-regime points and one-sentence selection signals.
- Any range-points cases with their `scale` plan.
- Which patterns from §2 you applied and where.
- Anything you treated as guideline rather than structural.

Be explicit; don't hedge. The commitment is what the validator and any reviewer will check your JSON against.

### Step 5: Emit JSON

Write the rubric JSON, consistent with the commitment. Verify:
- IDs are dot-path-style and unique.
- Every `one_of` parent's children have `selection_signal`.
- Every `sum` parent's children's `points.default` sum to the parent's `points.default`.
- Every `one_of` parent's `points.default` ≥ max of children's defaults.
- Children under `satisfied_when` nodes have no `points`.
- Top-level `one_of` rubrics include a `no-progress` regime at 0 points.
- Range points have `min`, `max`, `default`, and a `scale` whose values include both `min` and `max`.

### Step 6: Self-check

Walk through and verify:
- Arithmetic adds up.
- Every regime's `selection_signal` is concrete enough to discriminate from siblings.
- No `description` contains compound questions ("X and Y and Z" — split into sub-criteria, see Anti-pattern C).
- All "0 points for X" statements are in guidelines, not leaves.
- All distributional/framing prose is in top-level guidelines, ordered first.
- The structural commitment in prose matches the JSON.

## §5 — Worked examples

### Example 1: USEMO 2020 P5 (multi-pattern)

**Source rubric (excerpt):**
> Most solutions are worth 0 or 7.
> - 0 points for no progress, special cases, etc.
> - 5-6 points for any tiny slip which the contestant could have easily repaired
> - 7 points for a correct solution
>
> For solutions which are not complete, the following items are additive:
> - 1 point for considering the spiral similarity taking R₁…R₁₀₀ to B₁…B₁₀₀ AND claiming that the center of the spiral similarity is the point of concurrency.
> - 1 point for claiming that ∠RᵢORᵢ₊₁ = π/50
> - 1 point for proving that O, Rᵢ, Pᵢ₊₁, Qᵢ₊₁ is concyclic
> - 1 point for further extending to proving O, Rᵢ, Rᵢ₊₁, Pᵢ₊₁, Qᵢ₊₁ concyclic
>
> There is no deduction for small configuration issues or small typos.
>
> Usually, computational approaches which are not essentially completed are judged by their geometric content. However, the following marks (not additive with anything) are possible:
> - 1 point for showing that the intersection point is quadratic AND making the general claim that a + bz + cz² is sufficient.

**Structural commitment:**

The top-level is `one_of` with five regimes: `complete` (7pt), `tiny-slip` (range 5–6), `partial-additive` (sum capped at 4), `complex-quadratic-claim` (1pt), and `no-progress` (0pt).

The `complete` and `tiny-slip` regimes are atomic with `satisfied_when: "all"`. The `tiny-slip` regime uses a range (Pattern 4) with `scale` distinguishing 6 (genuinely tiny: typos, single missing equalities) from 5 (more substantial: missing degenerate cases, justified-but-not-shown algebra).

The `partial-additive` regime is `sum` over four 1pt items. The first item ("spiral similarity AND concurrency claim") is atomic with `satisfied_when: "all"` over two sub-criteria, per Anti-pattern C — the source uses "AND" so we split into sharp sub-criteria.

The `complex-quadratic-claim` regime is its own top-level sibling because the source explicitly says "not additive with anything" (Pattern 3). It's atomic with `satisfied_when: "all"` over two sub-criteria.

The `no-progress` regime (0pt) is the explicit fallback; without it, papers that don't match other regimes have no valid `selected` value.

Distributional guidance: "Most solutions are worth 0 or 7" is Pattern 9; goes in top-level guidelines, ordered first. "No deduction for small configuration issues or small typos" is grader guidance; also guidelines. "Computational approaches are judged by geometric content" is grader guidance; guidelines.

No "0 points for X" enumerations beyond the 0-pt regime itself; no patterns 1, 2, 5, 6, 7, 8, 10 apply.

**rubric JSON:**

```json
{
  "rubric_version": "1.0",
  "id": "usemo-2020-p5",
  "description": "Show that the 50 specified diagonals of a colored 200-gon are concurrent.",
  "points": 7,
  "combinator": "one_of",
  "guidelines": [
    "Most solutions are worth 0 or 7. The partial-credit regimes exist for the rare in-between cases; do not stretch to award partial credit on papers that should be 0 or 7.",
    "No deduction for small configuration issues (e.g., not using directed angles) or small typos.",
    "Computational approaches that are not essentially completed are normally judged by their geometric content and do not earn marks beyond what the partial-additive items provide. The complex-quadratic-claim regime is the explicit exception."
  ],
  "children": [
    {
      "id": "complete",
      "selection_signal": "Solution is fully correct.",
      "points": 7, "satisfied_when": "all",
      "children": [
        { "id": "complete.proof", "description": "Complete and correct proof of concurrency." }
      ]
    },
    {
      "id": "tiny-slip",
      "selection_signal": "Solution is essentially complete but contains a slip the contestant could have easily repaired.",
      "points": {
        "min": 5, "max": 6, "default": 6,
        "scale": [
          { "value": 6, "criterion": "Slip is genuinely tiny: an obvious-from-context typo, a single missing equality in an angle chase, a notational inconsistency that doesn't affect the argument." },
          { "value": 5, "criterion": "Slip is more substantial but still easily reparable: a missing degenerate or boundary case, a justified-but-not-shown algebraic step, or a missing case in a degree-counting argument." }
        ]
      },
      "satisfied_when": "all",
      "children": [
        { "id": "tiny-slip.essentially-correct", "description": "Argument is essentially complete and correct modulo a tiny easily-reparable slip." }
      ]
    },
    {
      "id": "partial-additive",
      "selection_signal": "Solution is incomplete and earns one or more of the four additive partial-credit items below.",
      "points": 4, "combinator": "sum",
      "children": [
        {
          "id": "partial-additive.spiral-similarity",
          "description": "The spiral-similarity-as-concurrency-center claim.",
          "points": 1, "satisfied_when": "all",
          "children": [
            { "id": "partial-additive.spiral-similarity.identifies", "description": "Identifies the spiral similarity taking R₁…R₁₀₀ to B₁…B₁₀₀." },
            { "id": "partial-additive.spiral-similarity.center-is-concurrency", "description": "Claims that the center of this spiral similarity is the concurrency point." }
          ]
        },
        { "id": "partial-additive.angle-claim", "description": "Claims that ∠RᵢORᵢ₊₁ = π/50.", "points": 1 },
        { "id": "partial-additive.concyclic-4", "description": "Proves that O, Rᵢ, Pᵢ₊₁, Qᵢ₊₁ are concyclic.", "points": 1 },
        { "id": "partial-additive.concyclic-5", "description": "Extends to proving O, Rᵢ, Rᵢ₊₁, Pᵢ₊₁, Qᵢ₊₁ are concyclic (five points on a circle).", "points": 1 }
      ]
    },
    {
      "id": "complex-quadratic-claim",
      "selection_signal": "Solution follows the complex-numbers approach: shows the intersection point is quadratic AND makes the general claim that a + bz + cz² is sufficient regardless of a, b, c. Non-additive with the synthetic partial items.",
      "points": 1, "satisfied_when": "all",
      "children": [
        { "id": "complex-quadratic-claim.quadratic", "description": "Shows the intersection point is a degree-2 polynomial in z." },
        { "id": "complex-quadratic-claim.general-claim", "description": "Makes the general claim that a + bz + cz² suffices." }
      ]
    },
    {
      "id": "no-progress",
      "description": "No-progress fallback regime.",
      "selection_signal": "Solution shows no progress, only handles special cases, or has geometric content not matching any regime above.",
      "points": 0
    }
  ]
}
```

### Example 2: USEMO 2025 P5 (pure ladder, Pattern 7)

**Source rubric (excerpt):**
> The crux is to realize that the problem is related to the surface area of subsets of integer lattices.
> - 1 point for claiming the answer α = 99/100.
> - 2 points for either establishing Azza's strategy, or proving α < 0.99 is losing for Azza, conditioned on the corollary.
> - 5 points for proving either bound as well as the corollary.
> - 5 points for proving both bounds conditioned on the corollary.
> - 7 points for proving both bounds as well as the corollary.

**Structural commitment:**

This is a pure `one_of` ladder (Pattern 7). The five items at 1/2/5/5/7 points are mutually exclusive regimes, picked by the highest matching state of completeness. The two 5pt items differ only in *what* is left assumed (the corollary, vs. one of the bounds).

The 2pt item uses `satisfied_when: "any"` (Pattern 5) over its two alternatives (Azza's strategy, conditioned-lower-bound), since either earns the same value.

The "either bound + corollary" 5pt regime nests `satisfied_when: "any"` for the bound (since either bound counts) inside its `satisfied_when: "all"` over [bound, corollary].

The "Conditional on the corollary" framing (assuming the corollary without proof) is Pattern 6 — encoded as a regime with appropriate selection signal, not as a predicate.

Add an explicit `no-progress` 0pt regime. The "crux is surface area" framing is mild distributional/intent guidance — goes in top-level guidelines.

**rubric JSON:**

```json
{
  "rubric_version": "1.0",
  "id": "usemo-2025-p5",
  "description": "Find the smallest α such that Azza can win when g > Cn^α.",
  "points": 7,
  "combinator": "one_of",
  "guidelines": [
    "Answer: α = 99/100.",
    "The corollary states: for any X ⊆ ℝ¹⁰⁰, the boundary set S = {(P,Q) : P ∈ X, Q ∉ X, P ∼ Q} satisfies |S| ≥ (1/100)·|X|^(99/100). The crux is recognizing the connection to integer-lattice surface area.",
    "A complete and accurate citation of Loomis-Whitney plus a proof that it implies the corollary counts as a full proof of the corollary. A reference to a 'well-known result' without proper citation does not."
  ],
  "children": [
    {
      "id": "complete",
      "selection_signal": "Solution proves both bounds AND the corollary (or cites Loomis-Whitney with full statement and implication argument).",
      "points": 7, "satisfied_when": "all",
      "children": [
        { "id": "complete.azza-strategy", "description": "Establishes Azza's strategy showing α=99/100 suffices." },
        { "id": "complete.lower-bound", "description": "Proves α < 99/100 is losing for Azza." },
        { "id": "complete.corollary", "description": "Proves the corollary, or cites and applies Loomis-Whitney with full statement." }
      ]
    },
    {
      "id": "both-bounds-conditional",
      "selection_signal": "Solution proves both bounds but assumes the corollary without proof (e.g., cites a 'well-known result' improperly).",
      "points": 5, "satisfied_when": "all",
      "children": [
        { "id": "both-bounds-conditional.azza-strategy", "description": "Establishes Azza's strategy." },
        { "id": "both-bounds-conditional.lower-bound", "description": "Proves α < 99/100 is losing." }
      ]
    },
    {
      "id": "one-bound-and-corollary",
      "selection_signal": "Solution proves either Azza's strategy or the lower bound (not both), AND proves the corollary.",
      "points": 5, "satisfied_when": "all",
      "children": [
        { "id": "one-bound-and-corollary.corollary", "description": "Proves the corollary." },
        {
          "id": "one-bound-and-corollary.one-bound",
          "description": "Proves at least one bound.",
          "satisfied_when": "any",
          "children": [
            { "id": "one-bound-and-corollary.one-bound.azza-strategy", "description": "Establishes Azza's strategy." },
            { "id": "one-bound-and-corollary.one-bound.lower-bound", "description": "Proves α < 99/100 is losing." }
          ]
        }
      ]
    },
    {
      "id": "one-bound-conditional",
      "selection_signal": "Solution proves Azza's strategy OR proves α < 0.99 is losing, conditioned on the corollary (assumed without proof).",
      "points": 2, "satisfied_when": "any",
      "children": [
        { "id": "one-bound-conditional.azza-strategy", "description": "Establishes Azza's strategy." },
        { "id": "one-bound-conditional.lower-bound-conditional", "description": "Proves α < 0.99 is losing for Azza, assuming the corollary." }
      ]
    },
    {
      "id": "answer-only",
      "selection_signal": "Solution claims α = 99/100 but does not establish either bound or the corollary.",
      "points": 1, "satisfied_when": "all",
      "children": [
        { "id": "answer-only.claim", "description": "Claims the answer α = 99/100." }
      ]
    },
    {
      "id": "no-progress",
      "description": "No-progress fallback regime.",
      "selection_signal": "No claim of the answer or any component above.",
      "points": 0
    }
  ]
}
```

## Output format

### Structural commitment

[3–8 paragraphs of prose, per Step 4]

### JSON
```json
{ ... }
```

That's the complete output. No preamble, no postamble.