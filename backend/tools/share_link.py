"""Turn a running Cloudflare quick tunnel into a link that works for everybody.

A quick tunnel invents a new hostname every time it starts. The deployed
frontend reads the Voice + Visual backend address at runtime - from `?ai=` in
the link - so a new hostname needs a new link rather than a new Vercel build.
Assembling that link by hand, correctly, at the start of every session is
exactly the sort of step that goes wrong in front of an audience, so this reads
the hostname out of cloudflared's own log and prints the finished link.

Run by `start-tunnel.bat`; also usable on its own:

    python -m tools.share_link --log tunnel.log
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

#: cloudflared prints the hostname inside a box of `|` characters, so anchor on
#: the URL itself rather than on the surrounding layout, which has changed
#: between releases.
TUNNEL_URL = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent


def frontend_url(env: dict[str, str | None]) -> str:
    """Where the public site lives.

    `PUBLIC_FRONTEND_URL` is the explicit answer. Falling back to the first
    https origin in `ALLOWED_ORIGINS` means an existing .env already has the
    right value: that list has to contain the frontend anyway, or the browser
    would refuse every call to this backend.
    """
    explicit = (env.get("PUBLIC_FRONTEND_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    for item in (env.get("ALLOWED_ORIGINS") or "").split(","):
        candidate = item.strip().rstrip("/")
        if candidate.startswith("https://"):
            return candidate
    return ""


def wait_for_tunnel(log_path: Path, timeout_seconds: float) -> str:
    """Poll cloudflared's log until it announces the hostname.

    The *last* hostname in the file is the live one. `start-tunnel.bat` deletes
    the log first, but Windows refuses to delete a file another cloudflared
    still holds open - so a tunnel left running from earlier keeps appending,
    and the file ends up holding that dead hostname ahead of the new one.
    Reading the first match handed out a link to a tunnel that had already
    stopped, which is indistinguishable from the machine being off.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            text = ""
        found = TUNNEL_URL.findall(text)
        if found:
            return found[-1]
        time.sleep(0.5)
    return ""


def copy_to_clipboard(text: str) -> bool:
    """Best effort. A missing clipboard must not fail the run."""
    try:
        subprocess.run("clip", input=text.encode("utf-16-le"), check=True, shell=True)
        return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", default=str(ROOT_DIR / "tunnel.log"))
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--out", default=str(ROOT_DIR / "SHARE_LINK.txt"))
    args = parser.parse_args(argv)

    env = {**dotenv_values(BACKEND_DIR / ".env"), **os.environ}
    tunnel = wait_for_tunnel(Path(args.log), args.timeout)
    if not tunnel:
        print("Khong tim thay dia chi tunnel trong log sau", args.timeout, "giay.")
        print("Xem cua so 'Clarivo tunnel' de biet cloudflared bao loi gi.")
        return 1

    site = frontend_url(env)
    if not site:
        print()
        print("  Dia chi backend AI:", tunnel)
        print()
        print("  Chua biet dia chi trang public. Dat PUBLIC_FRONTEND_URL trong")
        print("  backend\\.env (vi du https://clarivo-kohl.vercel.app) de script")
        print("  tu ghep link chia se.")
        return 0

    share = f"{site}/?ai={tunnel}"
    Path(args.out).write_text(share + "\n", encoding="utf-8")
    copied = copy_to_clipboard(share)

    print()
    print("  " + "=" * 66)
    print("   LINK GUI CHO NGUOI KHAC (da co san dia chi AI ben trong):")
    print()
    print("   " + share)
    print()
    print("  " + "=" * 66)
    print("   - Da luu vao SHARE_LINK.txt" + (" va copy vao clipboard." if copied else "."))
    print("   - Ai mo link nay se dung duoc ca Giong noi va Hinh anh.")
    print("   - Link chi song khi cua so tunnel con mo va may nay con bat.")
    print("   - Lan sau chay lai se ra link khac: gui lai link moi.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
