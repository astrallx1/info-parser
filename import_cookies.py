"""Convert a Cookie-Editor export (array of cookie objects) into the Playwright
storage_state format the parser needs, and write it to cookies.json.

Usage:
    .venv/bin/python import_cookies.py <cookie_editor_export.json> [out=cookies.json]

Cookie-Editor exports an ARRAY like:
  [{"name":"auth_token","value":"...","domain":".x.com","path":"/",
    "expirationDate":1789..., "secure":true,"httpOnly":true,
    "sameSite":"no_restriction","session":false}, ...]
Playwright storage_state wants:
  {"cookies":[{"name","value","domain","path","expires","httpOnly",
               "secure","sameSite"(Strict|Lax|None)}], "origins":[]}
"""
import json, os, sys

# The parser only ever talks to X, so nothing else belongs in this file. Both doors
# into it — this converter and setup_x_login.py — filter through here, because a
# browser export can carry every site the browser knows.
X_DOMAINS = ("x.com", "twitter.com")

SAMESITE = {"no_restriction": "None", "none": "None", "lax": "Lax",
            "strict": "Strict", "unspecified": "Lax", "": "Lax", None: "Lax"}

def _is_x(domain: str) -> bool:
    # match on the domain LABELS, not as a substring: "notx.com.evil.example"
    # contains "x.com" and is not X.
    d = (domain or "").lstrip(".").lower()
    return any(d == x or d.endswith("." + x) for x in X_DOMAINS)


def x_only(state: dict) -> dict:
    """Everything that is not X, removed. Origins (localStorage) go wholesale: the
    scraper authenticates with cookies."""
    return {"cookies": [c for c in state.get("cookies", []) if _is_x(c.get("domain"))],
            "origins": []}


def write_state(state: dict, path: str) -> None:
    """Write the FILTERED state, owner-only. A live X session in plain text stays
    off other accounts on the machine."""
    filtered = x_only(state)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(filtered, fh, ensure_ascii=False, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def convert(raw):
    arr = raw.get("cookies", raw) if isinstance(raw, dict) else raw
    out = []
    for c in arr:
        exp = c.get("expires", c.get("expirationDate"))
        exp = -1 if (exp is None or c.get("session")) else float(exp)
        ss = c.get("sameSite")
        ss = SAMESITE.get(ss.lower() if isinstance(ss, str) else ss, "Lax")
        out.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".x.com"),
            "path": c.get("path", "/"),
            "expires": exp,
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", True)),
            "sameSite": ss,
        })
    return x_only({"cookies": out, "origins": []})

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    src = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "cookies.json"
    with open(src, encoding="utf-8") as f:
        raw = json.load(f)
    state = convert(raw)
    names = {c["name"] for c in state["cookies"]}
    need = {"auth_token", "ct0"}
    missing = need - names
    write_state(state, out_path)
    print(f"wrote {len(state['cookies'])} cookies -> {out_path}")
    print("has auth_token:", "auth_token" in names, "| has ct0:", "ct0" in names)
    if missing:
        print(f"WARNING: missing essential cookies: {missing} "
              f"(export while logged into X on x.com)")

if __name__ == "__main__":
    main()
