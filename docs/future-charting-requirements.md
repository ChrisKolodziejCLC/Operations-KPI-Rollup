# Future charting requirements

Status: Loaded was approved in v0.26.0. Staged, Painted, Repaint %, and Finesse Effectiveness were approved and implemented in v0.32.0. PPY and FTY remain future product intent until their metric contracts are separately approved.

## Goal and target lines

Chris's charting rule is:

- **Goal:** the theoretical requirement.
- **Target:** close 25% of the gap from an approved historical baseline toward that requirement.

```text
T = theoretical requirement
A = approved historical baseline

Goal = T
Target = A + 0.25 × (T - A)
```

For Loaded, v0.26.0 freezes the reviewed available-history baseline from 2026-09-08 through 2026-11-15 rather than pretending a trailing 12 months exists. Its goals are 12 carts/hour and 36 pieces/hour. Net time is first distinct-cart load through last distinct-cart load, less a standard 30-minute lunch on completed days spanning at least six hours; partial days are not scored.

Version 0.32.0 applies the same frozen baseline window and 25% gap-closing formula to four approved contracts: Staged uses close-of-day queue snapshots with minimum goals of 12 carts and 36 pieces; Painted uses first distinct-cart paint exit through last distinct-cart paint exit, the same lunch rule, and goals of 10 carts/hour and 30 pieces/hour; Repaint uses a weighted 4% goal where lower is better; Finesse Effectiveness uses a weighted 90% goal where higher is better. PPY and FTY must separately approve baseline grain, direction, and comparable-time rules before this format is copied.
