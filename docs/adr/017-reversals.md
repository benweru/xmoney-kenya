# 017. Reversals are new entries; large ones need a second actor

- Status: Accepted
- Date: 2026-10-20

## Context

The ledger cannot be edited ([002](002-ledger-design.md)). Mistakes still happen: a send to the wrong handle, a top-up credited in error. M3 asks for compensating entries and maker-checker for large amounts. The public demo has no staff login ([006](006-open-demo-protections.md)), so an HTTP reverse-and-credit would be a minting hole, the same reason suspense is CLI-only ([016](016-suspense.md)).

## Decision

**A reversal is a new journal entry** whose postings are the original lines with debit and credit swapped. The original row does not change. Idempotency key `reverse:{reversal_id}`. At most one proposed or posted reversal per original entry; a rejected proposal can be tried again.

**Size.** `amount_cents` is the sum of the original debit lines. At or above `REVERSAL_MAKER_CHECKER_CENTS` (default KES 100) the row stays `proposed` until a *different* actor approves. Below that, the maker's propose posts immediately (checker stays null). The maker cannot approve or reject their own proposal.

**Overdraft.** Wallets that may not go negative are locked and checked before post. If the recipient has already spent the inbound credit, the reversal is refused.

**CLI only (`xmoney-reversal`).** Actor names are labels on the row, not sessions. Console staff auth can wrap the same service later.

## Consequences

- Reversing a P2P send that charged a fee also reverses the fee leg.
- Actor strings can be forged until console login exists; the control is the two-person *process*, not cryptography.
- Partial reversals are not this slice.

## Alternatives considered

- **Edit the original postings.** Forbidden by the ledger seal.
- **Always require two people.** Correct for a bank; noisy for reversing a KES 4 test send.
- **HTTP with a shared staff cookie.** The open demo would let visitors reverse each other.
