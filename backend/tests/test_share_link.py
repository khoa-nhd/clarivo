"""The share link that connects a visitor's browser to this machine.

A quick tunnel's hostname changes on every start, so the link is rebuilt every
session. It is assembled once, here, rather than by hand at the start of a
demo - and these tests pin the two things that would silently produce a link
that does not work: reading the wrong hostname out of the log, and guessing the
wrong public site.
"""

import sys
import types

_ov = types.ModuleType("openvino")
_ov.Core = object
sys.modules.setdefault("openvino", _ov)

from tools.share_link import TUNNEL_URL, frontend_url, wait_for_tunnel

CLOUDFLARED_LOG = """
2026-09-30T09:12:01Z INF Thank you for trying Cloudflare Tunnel.
2026-09-30T09:12:03Z INF +--------------------------------------------------------+
2026-09-30T09:12:03Z INF |  Your quick Tunnel has been created! Visit it at:       |
2026-09-30T09:12:03Z INF |  https://calm-river-plate-9f3a.trycloudflare.com       |
2026-09-30T09:12:03Z INF +--------------------------------------------------------+
"""


def test_the_hostname_is_read_out_of_the_log(tmp_path):
    log = tmp_path / "tunnel.log"
    log.write_text(CLOUDFLARED_LOG, encoding="utf-8")
    assert wait_for_tunnel(log, 1.0) == "https://calm-river-plate-9f3a.trycloudflare.com"


def test_the_box_drawing_is_not_taken_as_part_of_the_hostname(tmp_path):
    """The URL sits inside a table of `|` and spaces; none of it belongs."""
    log = tmp_path / "tunnel.log"
    log.write_text(CLOUDFLARED_LOG, encoding="utf-8")
    found = wait_for_tunnel(log, 1.0)
    assert found.endswith(".trycloudflare.com")
    assert " " not in found and "|" not in found


def test_a_missing_log_times_out_rather_than_raising(tmp_path):
    assert wait_for_tunnel(tmp_path / "absent.log", 0.2) == ""


def test_a_log_without_a_url_yet_times_out(tmp_path):
    log = tmp_path / "tunnel.log"
    log.write_text("INF Starting tunnel\n", encoding="utf-8")
    assert wait_for_tunnel(log, 0.2) == ""


def test_an_explicit_frontend_url_wins():
    env = {
        "PUBLIC_FRONTEND_URL": "https://clarivo-kohl.vercel.app/",
        "ALLOWED_ORIGINS": "https://something-else.vercel.app",
    }
    assert frontend_url(env) == "https://clarivo-kohl.vercel.app"


def test_the_frontend_falls_back_to_the_first_https_allowed_origin():
    env = {"ALLOWED_ORIGINS": "http://localhost:5173,https://clarivo-kohl.vercel.app"}
    assert frontend_url(env) == "https://clarivo-kohl.vercel.app"


def test_a_localhost_only_origin_list_yields_no_public_site():
    """Better to say nothing than to hand out a link to http://localhost."""
    assert frontend_url({"ALLOWED_ORIGINS": "http://localhost:5173"}) == ""


def test_missing_configuration_is_not_an_error():
    assert frontend_url({}) == ""


def test_the_pattern_ignores_a_lookalike_domain():
    assert TUNNEL_URL.search("https://evil-trycloudflare.com.attacker.example") is None


def test_the_newest_hostname_wins_when_an_old_tunnel_kept_writing(tmp_path):
    """The exact failure this caused: a link to a tunnel that had stopped.

    start-tunnel.bat deletes the log before starting, but Windows will not
    delete a file a still-running cloudflared holds open. The old process keeps
    appending, so its dead hostname sits above the new one.
    """
    log = tmp_path / "tunnel.log"
    log.write_text(
        "INF |  https://old-and-dead-1111.trycloudflare.com  |\n"
        "INF |  https://new-and-live-2222.trycloudflare.com  |\n",
        encoding="utf-8",
    )
    assert wait_for_tunnel(log, 1.0) == "https://new-and-live-2222.trycloudflare.com"


def test_a_single_hostname_repeated_is_still_that_hostname(tmp_path):
    """cloudflared reprints the URL on reconnect; that is not a new tunnel."""
    log = tmp_path / "tunnel.log"
    line = "INF |  https://steady-4444.trycloudflare.com  |\n"
    log.write_text(line * 3, encoding="utf-8")
    assert wait_for_tunnel(log, 1.0) == "https://steady-4444.trycloudflare.com"
