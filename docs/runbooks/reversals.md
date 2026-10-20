# Reverse a journal entry

Sandbox-only. Compensating entry; the original is not edited. No HTTP route.

## When

A send, top-up credit, or other journal entry should not stand. If the recipient has already spent the money, the reversal will refuse rather than overdraw them.

## Small amounts (under `REVERSAL_MAKER_CHECKER_CENTS`, default KES 100)

```bash
make reversal ARGS='propose --entry <journal-entry-uuid> --reason "wrong payee" --maker alice'
```

That posts immediately.

## Large amounts

```bash
make reversal ARGS='propose --entry <journal-entry-uuid> --reason "fraud" --maker alice'
make reversal ARGS=list
make reversal ARGS='approve --id <reversal-uuid> --checker bob'
# or
make reversal ARGS='reject --id <reversal-uuid> --checker bob --reason "keep it"'
```

`alice` cannot approve or reject her own proposal.

## Find the entry id

Wallet history items include `entry_id`. Transfers store `journal_entry_id` on the `transfers` row.
