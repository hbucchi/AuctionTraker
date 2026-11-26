import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "write_credentials", Path(__file__).parents[1] / "scripts" / "write_credentials.py"
)
wc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wc)

BODY = "QUJD" * 40  # fake base64, 160 chars
KEY = {
    "type": "service_account",
    "project_id": "p",
    "client_email": "x@p.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\n" + BODY[:64] + "\n" + BODY[64:128] + "\n" + BODY[128:] + "\n-----END PRIVATE KEY-----\n",
}
CANONICAL = KEY["private_key"]


@pytest.mark.parametrize(
    "mangle",
    [
        lambda s: s,                                   # clean paste
        lambda s: s.replace("\\n", "\n"),              # escapes became real line breaks
        lambda s: s[:150] + "\n" + s[150:],            # wrap inside the key
        lambda s: "```json\n" + s + "\n```",           # pasted with a code fence
    ],
)
def test_repairs_common_paste_damage(mangle):
    assert wc.repair(mangle(json.dumps(KEY, indent=2)))["private_key"] == CANONICAL


def test_rejects_truncated_key():
    with pytest.raises(ValueError):
        wc.repair(json.dumps(KEY)[:120])
