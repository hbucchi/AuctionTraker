"""Write the service-account key from an environment variable to a file,
repairing damage that copy-pasting often does to it.

    FIREBASE_SA='<secret>' python scripts/write_credentials.py /path/to/sa.json

Pasting the key JSON into a web form (especially on a phone) can turn the
"\\n" sequences inside ``private_key`` into real line breaks, or add line
wraps in the middle of it, which makes the JSON invalid. This script:

1. keeps only the text from the first "{" to the last "}",
2. parses it leniently (real line breaks allowed inside strings),
3. rebuilds the PEM private key in canonical 64-character lines,
4. writes clean JSON with permissions 600.

It never prints the secret or any part of it.
"""

from __future__ import annotations

import json
import os
import re
import sys

REQUIRED = ("type", "project_id", "private_key", "client_email")


def repair(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("the secret doesn't contain a JSON object ({ ... })")
    data = json.loads(raw[start : end + 1], strict=False)
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        raise ValueError(f"the key JSON is missing: {', '.join(missing)}")
    if data["type"] != "service_account":
        raise ValueError("this JSON is not a service-account key")

    pem = data["private_key"].replace("\\n", "\n")
    m = re.search(r"-----BEGIN ([A-Z ]+)-----(.*?)-----END \1-----", pem, re.S)
    if not m:
        raise ValueError("private_key has no BEGIN/END PRIVATE KEY markers (was it cut off?)")
    label, body = m.group(1), re.sub(r"\s+", "", m.group(2))
    if not re.fullmatch(r"[A-Za-z0-9+/]+=*", body):
        raise ValueError("private_key contains characters that can't be part of a key")
    lines = [body[i : i + 64] for i in range(0, len(body), 64)]
    data["private_key"] = f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"
    return data


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: write_credentials.py <output-path>", file=sys.stderr)
        return 2
    raw = os.environ.get("FIREBASE_SA", "")
    if not raw.strip():
        print("FIREBASE_SA is empty: is the FIREBASE_SERVICE_ACCOUNT secret set?", file=sys.stderr)
        return 1
    try:
        data = repair(raw)
    except (ValueError, json.JSONDecodeError) as e:
        # json errors include a position, never the content
        print(f"could not read the service-account key: {e}", file=sys.stderr)
        return 1
    out = sys.argv[1]
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    print(f"credentials written for project {data['project_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
