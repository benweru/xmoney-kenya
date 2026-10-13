# 002. Ledger: double-entry, integer cents, balances derived from postings

- Status: Accepted
- Date: 2026-10-13

## Context

A wallet's ledger is the record of who is owed what. If it can drift, every other feature is built on sand. The failure modes we care about are float rounding, a write that moves money on one side only, a retried request that posts twice, concurrent writes that interleave, and history that is quietly edited.

## Decision

**Money is integer KES cents.** `amount_cents` is a Postgres `bigint` and a Python `int`. Floats are rejected at the API (`StrictInt`) and in the service. M-PESA collects whole shillings, so the STK adapter rejects amounts not divisible by 100, but the ledger keeps cents so fees can be fractions of a shilling.

**Double-entry.** Every change is a journal entry with two or more postings; each posting is a positive amount, a direction (debit or credit), and an account. Debits must equal credits. Accounts have a type (asset, liability, equity, income, expense) and a normal side. A customer wallet is a liability, because we owe the customer that balance. System accounts are the M-PESA float and clearing (assets), fees (income), and suspense (liability).

**Balances are derived, never stored.** A balance is the sum of an account's postings, signed by its normal side. There is no `balance` column to fall out of step. If reads become slow, a snapshot table can be added later, rebuilt from postings and checked against them.

**The database enforces the invariants, not only the service:**

- A deferred constraint trigger rejects any entry whose debits do not equal its credits, or that has fewer than two postings, at commit.
- Postings, entries, and accounts cannot be updated, deleted, or truncated.
- Postings can only be inserted in the transaction that created their entry, so a committed entry cannot gain lines.
- Corrections are new compensating entries, never edits.

**Idempotency.** Every entry carries a unique idempotency key and a SHA-256 of its economic content (description, external reference, and postings sorted so order does not matter). Replaying the same key and content returns the original entry; the same key with different content is a 409 conflict. Concurrent replays race on the unique index, and the loser re-reads the winner's entry.

**Concurrency.** `post_entry` owns its transaction and locks the accounts it touches with `SELECT … FOR UPDATE`, in account-id order so concurrent posts cannot deadlock. Overdraft rules (milestone M1) will check balances under those locks.

## Consequences

- An unbalanced or edited ledger requires bypassing database triggers, not just a service bug.
- Reading a balance is an aggregate query. That is fine at sandbox scale and is the honest baseline before any caching.
- Mistakes cannot be fixed in place. Reversals and refunds need their own flows and, for large amounts, a second approver (M3).
- Because `post_entry` commits, a caller cannot yet combine a ledger post with other writes in one transaction. The M1 payment state machine will need a variant that posts inside the caller's transaction (for example, under a savepoint) so that a payment row and its ledger entry commit together.

## Alternatives considered

- **Decimal amounts.** Exact, but easy to mix with floats at the edges and awkward across JSON. Integer cents remove the question.
- **A balance column updated on each post.** Fast reads, but two sources of truth that can disagree. Derivation first; a checked snapshot later if needed.
- **Single-entry (a list of +/- amounts per wallet).** Cannot show where money came from or prove the books balance.
- **Application-only checks.** Any bug, script, or manual SQL could unbalance the books.
