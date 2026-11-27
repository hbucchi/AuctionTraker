"""Build a self-contained preview of the web app (no Firebase) into a folder.

    python scripts/build_preview.py data/<run-id> out/preview

The preview page loads listings.json and strategy-fields.json next to it and
keeps strategies in the browser. strategy.js is inlined because some preview
hosts only allow scripts from the page itself.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    run_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "auction_tracker", "export-web", str(run_dir), str(out / "listings.json")], check=True, cwd=ROOT)
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    head = page.split("<!-- preview:strip-above -->", 1)[1].split("<!-- preview:strip-below -->", 1)[0]
    body = page.split("<body>", 1)[1].rsplit("</body>", 1)[0]
    def inline(name: str) -> str:
        js = (ROOT / "web" / name).read_text(encoding="utf-8")
        js = "\n".join(line for line in js.splitlines() if not line.startswith("import "))
        return js.replace("export function", "function").replace("export const", "const")

    body = body.replace('import { matchesStrategy, nextDeadline } from "./strategy.js";', inline("roe.js") + "\n" + inline("strategy.js"))
    body = body.replace('import { roeRange, roeAssumptions, flip } from "./roe.js";', "")
    (out / "index.html").write_text(head.strip() + "\n" + body.strip() + "\n", encoding="utf-8")
    (out / "firebase-config.js").write_text("// preview build: no Firebase\nwindow.FIREBASE_CONFIG = null;\n")
    shutil.copy(ROOT / "web" / "strategy-fields.json", out / "strategy-fields.json")
    shutil.copy(ROOT / "web" / "valuation-meta.json", out / "valuation-meta.json")
    shutil.copy(ROOT / "web" / "brazil-states.json", out / "brazil-states.json")
    print(f"preview written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
