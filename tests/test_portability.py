"""Rules that only break on the platform nobody is developing on.

The owner's normal machine is Windows and he is on the Mac until roughly the end of
August, so these went unnoticed until CI started running the suite on windows-latest.
Both of the checks below correspond to a failure that actually happened there.
"""
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCES = (glob.glob(os.path.join(ROOT, "topicparser", "**", "*.py"), recursive=True)
           + glob.glob(os.path.join(ROOT, "*.py")))

def _open_calls(src):
    """Every `open(...)` with its FULL argument list. Balanced parens on purpose: a
    regex that stops at the first `)` cuts `open(_backup_path(name), encoding=...)`
    in half and reports a file that is perfectly fine."""
    for m in re.finditer(r"(?<![\w.])open\(", src):
        i, depth = m.end() - 1, 0
        while i < len(src):
            if src[i] == "(":
                depth += 1
            elif src[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        yield m.start(), src[m.start():i + 1]


def test_every_text_file_is_opened_with_an_explicit_encoding():
    """Python picks the LOCALE encoding when none is given: UTF-8 on the Mac, cp1252
    on a default Windows install. `import_cookies.py` read the cookie export that way
    and died with a UnicodeDecodeError on the first non-ASCII byte — on Windows only.
    """
    offenders = []
    for path in SOURCES:
        src = open(path, encoding="utf-8").read()
        for start, call in _open_calls(src):
            if "encoding" in call or re.search(r"['\"][rwax+]*b[rwax+]*['\"]", call):
                continue
            line = src[:start].count("\n") + 1
            offenders.append(f"{os.path.relpath(path, ROOT)}:{line}: {call.strip()[:70]}")
    assert offenders == [], "text open() without encoding=: " + "; ".join(offenders)


def test_no_source_file_hardcodes_a_posix_home():
    """`os.path.expanduser` reads USERPROFILE on Windows and ignores HOME, so a path
    built from "/Users/..." or "/home/..." is a Mac-only assumption."""
    offenders = []
    for path in SOURCES:
        src = open(path, encoding="utf-8").read()
        for m in re.finditer(r'["\'](/Users/|/home/)[\w./-]*["\']', src):
            line = src[:m.start()].count("\n") + 1
            offenders.append(f"{os.path.relpath(path, ROOT)}:{line}: {m.group(0)}")
    assert offenders == [], "hardcoded home: " + "; ".join(offenders)


def test_shipped_code_carries_no_ukrainian_but_the_two_places_that_need_it():
    """`publish.sh` refuses when Ukrainian reaches the shipped product, and it was
    ALREADY refusing: `index.html` had grown a second Cyrillic comment, so the public
    repo could not be built at all. A refusal at publish time is the wrong place to
    find that out — the suite is."""
    import pathlib
    import re

    cyr = re.compile(r"[Ѐ-ӿ]")
    allowed = {"topicparser/collectors/x.py",   # X's reply label, one per UI language
               "topicparser/ranker.py",         # the Cyrillic range the repair matches
               "topicparser/ui/index.html"}     # ONE css comment, checked below
    root = pathlib.Path(".")
    bad = []
    for p in list(root.glob("*.py")) + list((root / "topicparser").rglob("*")):
        if not p.is_file() or p.suffix not in {".py", ".html", ".txt"}:
            continue
        rel = p.as_posix()
        if rel in allowed or "/prompts/" in rel or "/lang/" in rel:
            continue
        if cyr.search(p.read_text(encoding="utf-8")):
            bad.append(rel)
    assert not bad, f"Ukrainian in shipped code: {bad}"

    ui = (root / "topicparser/ui/index.html").read_text(encoding="utf-8").splitlines()
    hits = [l for l in ui if cyr.search(l)]
    assert len(hits) == 1, f"index.html: {len(hits)} Cyrillic lines, publish.sh allows 1"
