# Future charting requirements

Status: retained product intent; not yet implemented.

## Goal and target lines

Chris's charting rule is:

- **Goal:** the theoretical requirement.
- **Target:** move 25% of the way from the trailing 12-month average toward the theoretical requirement.

Working formula:

```text
T = theoretical requirement
A12 = trailing 12-month average

Goal = T
Target = A12 + 0.25 × (T - A12)
```

This preserves the thought process as a 25% closure of the gap between actual 12-month performance and the theoretical requirement. Before implementation, confirm that this is the intended interpretation of “theoretical minus 12-month average, plus 25%,” along with the approved 12-month averaging grain and any handling needed for lower-is-better metrics.
