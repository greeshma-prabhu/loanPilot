"""Interactive utility for creating a secrets-compatible scrypt hash."""

from getpass import getpass

from loanpilot.auth.core import make_password_hash


def main() -> None:
    """Prompt twice without echo and print only the hash configuration line."""
    password = getpass("Password: ")
    confirmation = getpass("Confirm password: ")
    if not password or password != confirmation:
        raise SystemExit("Passwords must be non-empty and match.")
    print(f'password_hash = "{make_password_hash(password)}"')


if __name__ == "__main__":
    main()
