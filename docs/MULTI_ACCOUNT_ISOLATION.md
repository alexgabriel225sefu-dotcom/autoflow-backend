# Multi-account isolation design

Multi-account state is scoped by the authenticated user id and the broker
account id. The pair is the security boundary; an account id by itself is
never a storage key, cache key, kill-switch key or UI identity.

The isolation contract is deliberately small:

- reads return only records whose user/account scope exactly matches the
  authenticated request;
- writes use copy-on-write records so callers cannot mutate stored state by
  retaining a reference;
- an account kill switch applies only to that user's account;
- a user-wide kill switch applies only to that user's accounts;
- no strategy, risk record or kill switch is looked up by account id alone;
- unknown or missing state is not treated as running or safe.

`tests/test_multi_account_isolation.py` is the executable contract. The UI and
account-control endpoint must not be expanded until this contract remains green
in the full test runner.
