#!/usr/bin/env python3
"""Generate JWT_SECRET and a Fernet CREDENTIAL_ENCRYPTION_KEY.

Usage: python3 infrastructure/scripts/gen-keys.py [path/to/.env]
If the .env file exists, the two keys are written into it in place;
otherwise they are printed to stdout. Uses only the standard library.
"""
import base64
import os
import re
import secrets
import sys

jwt_secret = secrets.token_urlsafe(64)
fernet_key = base64.urlsafe_b64encode(os.urandom(32)).decode()

path = sys.argv[1] if len(sys.argv) > 1 else ".env"
if not os.path.exists(path):
    print(f"JWT_SECRET={jwt_secret}")
    print(f"CREDENTIAL_ENCRYPTION_KEY={fernet_key}")
    sys.exit(0)

with open(path, encoding="utf-8") as fh:
    content = fh.read()
for key, value in (("JWT_SECRET", jwt_secret), ("CREDENTIAL_ENCRYPTION_KEY", fernet_key)):
    line = f"{key}={value}"
    if re.search(rf"(?m)^{key}=", content):
        content = re.sub(rf"(?m)^{key}=.*$", lambda _m, line=line: line, content)
    else:
        content += f"\n{line}\n"
with open(path, "w", encoding="utf-8") as fh:
    fh.write(content)
print(f"Wrote JWT_SECRET and CREDENTIAL_ENCRYPTION_KEY to {path}")
