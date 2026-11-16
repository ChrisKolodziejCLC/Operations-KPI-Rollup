# Future charting requirements

Status: Loaded goals and targets were approved and implemented in v0.26.0; the rule remains future product intent for other metrics until each metric owner approves its baseline grain and direction.

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

For Loaded, v0.26.0 freezes the reviewed available-history baseline from 2026-09-08 through 2026-11-15 rather than pretending a trailing 12 months exists. Its Loaded goals are 12 carts/hour and 36 pieces/hour; 10 carts/hour and 30 pieces/hour are reserved for the separate Carts / Pieces Painted metric. Net time is first distinct-cart load through last distinct-cart load, less a standard 30-minute lunch on completed days spanning at least six hours; partial days are not scored. Other tiles must separately approve the baseline period, higher- or lower-is-better direction, and comparable-time rules before this format is copied.
