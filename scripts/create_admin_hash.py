#!/usr/bin/env python3
"""
Generate a bcrypt hash for an admin credential.

Usage:
    python scripts/create_admin_hash.py alice@company.com mypassword

Output (copy the JSON fragment into your ADMIN_CREDENTIALS env var):
    "alice@company.com": "$2b$12$..."

To set up ADMIN_CREDENTIALS with multiple admins, build a JSON object:
    ADMIN_CREDENTIALS='{"alice@company.com":"$2b$12$...","bob@company.com":"$2b$12$..."}'
"""

import sys


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <email> <password>", file=sys.stderr)
        sys.exit(1)

    email = sys.argv[1].strip().lower()
    password = sys.argv[2]

    try:
        import bcrypt
    except ImportError:
        print("ERROR: bcrypt is not installed. Run: pip install bcrypt", file=sys.stderr)
        sys.exit(1)

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
    print(f'"{email}": "{hashed}"')


if __name__ == "__main__":
    main()
