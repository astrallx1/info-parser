"""The UA must name the machine the scrape actually runs on.

It was hardcoded to macOS. On Windows the browser then announced "Macintosh" while
the page's own `navigator.platform` answered "Win32" — a contradiction no real
browser produces, so the one string meant to look ordinary was itself the tell.
`stealth.py` patches `webdriver`, plugins, languages and WebGL but NOT `platform`,
so nothing else was covering for it. The owner's normal machine is Windows."""
from topicparser.collectors import x


def test_windows_says_windows():
    assert "Windows NT 10.0; Win64; x64" in x.real_ua("Windows")
    assert "Macintosh" not in x.real_ua("Windows")


def test_macos_says_macintosh():
    assert "Macintosh; Intel Mac OS X" in x.real_ua("Darwin")


def test_linux_says_x11():
    assert "X11; Linux x86_64" in x.real_ua("Linux")


def test_an_unknown_system_still_returns_a_usable_ua():
    # never raise and never return an empty UA: a blank one is a louder tell than
    # a wrong one, and the scrape must still run.
    ua = x.real_ua("Plan9")
    assert ua.startswith("Mozilla/5.0 (") and "Chrome/" in ua


def test_every_platform_shares_one_chrome_version():
    # the version lives in ONE place, or the three strings drift apart and the odd
    # one out becomes the fingerprint.
    versions = {u.split("Chrome/")[1].split(" ")[0]
                for u in (x.real_ua(s) for s in ("Windows", "Darwin", "Linux"))}
    assert len(versions) == 1


def test_the_default_follows_the_running_machine(monkeypatch):
    monkeypatch.setattr(x.platform, "system", lambda: "Windows")
    assert "Windows NT" in x.real_ua()
