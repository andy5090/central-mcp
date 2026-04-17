from __future__ import annotations

from central_mcp import scrub


def test_ansi_removal_strips_csi_sequences() -> None:
    s = "\x1b[32mgreen\x1b[0m plain \x1b[1;31mred-bold\x1b[0m"
    assert scrub.scrub_ansi(s) == "green plain red-bold"


def test_ansi_removal_leaves_plain_text_alone() -> None:
    assert scrub.scrub_ansi("no escapes here") == "no escapes here"


def test_secret_patterns_redact_common_tokens() -> None:
    # Tokens are split across string literals so secret-scanners don't flag
    # this test file as containing real credentials.
    s = (
        "sk-ant-" + "abcdefghijklmnop1234567890 "
        "sk-" + "abcdefghijklmnop1234567890 "
        "ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890 "
        "AKIA" + "ABCDEFGHIJKLMNOP "
        "AIzaSy" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456 "
        "xoxb-" + "12345-67890-abcdefghijklmnop "
        "Bearer " + "abcdefghijklmnopqrstuvwxyz"
    )
    out = scrub.scrub_secrets(s)
    assert "sk-ant" not in out
    assert "ghp_" not in out
    assert "AKIA" not in out
    assert "AIza" not in out
    assert "xoxb-" not in out
    assert "Bearer abcdefghij" not in out
    assert out.count("***REDACTED***") >= 6


def test_kv_heuristic_redacts_inline_assignments() -> None:
    s = 'API_KEY="verysecret12345"\nother=stuff\ntoken: secrettoken_98765'
    out = scrub.scrub_secrets(s)
    assert "verysecret12345" not in out
    assert "secrettoken_98765" not in out
    # Non-secret KV remains untouched.
    assert "other=stuff" in out


def test_scrub_respects_opt_out_flags() -> None:
    s = "\x1b[31msk-ant-secret1234567890ABCDEFGH\x1b[0m"
    assert scrub.scrub(s, ansi=False, secrets=False) == s
    assert "\x1b[" not in scrub.scrub(s, ansi=True, secrets=False)
    assert "sk-ant-secret" not in scrub.scrub(s, ansi=False, secrets=True)
