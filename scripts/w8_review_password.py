"""Generate a local review password verifier without command-line secrets."""

from __future__ import annotations

import getpass

from egis_soc.w8_auth import make_password_hash


def main() -> int:
    first = getpass.getpass("Local analyst review password (12+ chars): ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise ValueError("password_confirmation_mismatch")
    print(make_password_hash(first))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
