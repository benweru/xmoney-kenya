"""Domain errors. HTTP status and error codes live with the exception."""


class XMoneyError(Exception):
    code = "error"
    http_status = 400


class InvalidAmount(XMoneyError):
    code = "invalid_amount"
    http_status = 422


class InvalidJournal(XMoneyError):
    code = "invalid_journal"
    http_status = 422


class InvalidIdempotencyKey(XMoneyError):
    code = "invalid_idempotency_key"
    http_status = 422


class UnbalancedEntry(XMoneyError):
    code = "unbalanced_entry"
    http_status = 422


class AccountNotFound(XMoneyError):
    code = "account_not_found"
    http_status = 404


class IdempotencyConflict(XMoneyError):
    code = "idempotency_conflict"
    http_status = 409


class LedgerError(XMoneyError):
    code = "ledger_error"
    http_status = 500


class InvalidHandle(XMoneyError):
    code = "invalid_handle"
    http_status = 422


class HandleTaken(XMoneyError):
    code = "handle_taken"
    http_status = 409


class InvalidPhone(XMoneyError):
    code = "invalid_phone"
    http_status = 422


class PhoneTaken(XMoneyError):
    code = "phone_taken"
    http_status = 409


class UserNotFound(XMoneyError):
    code = "handle_not_found"
    http_status = 404


class InvalidPaymentRequest(XMoneyError):
    code = "invalid_payment_request"
    http_status = 422


class CallbackParseError(XMoneyError):
    code = "callback_parse_error"
    http_status = 422


class ProviderError(XMoneyError):
    code = "provider_error"
    http_status = 502

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.http_status = status_code


class SandboxViolation(XMoneyError):
    code = "sandbox_violation"
    http_status = 403
