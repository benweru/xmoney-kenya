# Critique: reversals

**Scope**: CLI full reversals with maker-checker above a threshold (ADR 017). Written 20 Oct 2026.

## Ordinary

Flip the signs and insert. Many ledgers call that a contra.

## Genuinely impressive

- The original entry is untouched, and a second reverse of the same entry is refused while one is proposed or posted.
- Spent funds block the reverse (recipient overdraft), which is the failure mode a reviewer will ask about first.

## Weakest parts, ranked

1. **Actors are strings.** There is no staff session; `bob` is whoever typed `--checker bob` (`reversals/cli.py`).
2. **Full reverse only.** A KES 1,000 send that should have been KES 100 needs a new send, not a partial contra.
3. **Threshold is config, not a policy table.** Changing `REVERSAL_MAKER_CHECKER_CENTS` does not re-open already-posted small reversals, which is correct, but there is no audit of who changed the threshold.

## What would raise the bar next

1. Console staff login, then the same service with real maker ≠ checker user ids.
2. Partial reversal of a remaining amount.
3. Tie a posted reversal to history as `reversal` instead of `other`.

## Fed into the plan

Finding 1 is console v1, already next on M3. This PR does not add HTTP.
