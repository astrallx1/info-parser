"""Read and write the `.env` beside the app.

Editing a dotfile by hand is the first wall for someone who does not write code, so
the settings screen writes it instead. The file is also hand-edited, and it carries
comments that explain every tuning knob — so a write REPLACES the lines it owns and
leaves everything else exactly where it was, rather than regenerating the file.
"""
import os
import re

_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def _strip_value(raw: str) -> str:
    """The value on a line, without a trailing `# comment` or surrounding quotes."""
    v = raw.strip()
    if v[:1] in ("'", '"'):
        quote = v[0]
        end = v.find(quote, 1)
        return v[1:end] if end > 0 else v[1:]
    return v.split("#", 1)[0].strip()


def _comment_of(raw: str) -> str:
    """The trailing `# comment` on a value line, or "". A knob's comment is the only
    thing explaining what it does, and one Save from the Settings screen rewrites all
    nine knob lines at once, so dropping it strips the file's whole explanation."""
    v = raw.strip()
    if v[:1] in ("'", '"'):
        end = v.find(v[0], 1)
        v = v[end + 1:] if end > 0 else ""
    i = v.find("#")
    return v[i:].strip() if i >= 0 else ""


def read_env(path: str) -> dict:
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.lstrip().startswith("#"):
                continue
            m = _LINE.match(line)
            if m:
                out[m.group(1)] = _strip_value(m.group(2))
    return out


def _format(value: str) -> str:
    v = "" if value is None else str(value)
    # a bare value with a space or a '#' would be truncated when read back
    if v == v.strip() and " " not in v and "#" not in v:
        return v
    # `.env` has no escape for a quote inside quotes, so the WRAPPER has to be the
    # other kind: `say "hi", crypto` wrapped in double quotes read back as `say `.
    # Both kinds at once is unwritable, and `tuning.validate` refuses it upstream.
    return f"'{v}'" if '"' in v else f'"{v}"'


def write_env(path: str, values: dict) -> None:
    """Set `values`, keep every other line — comments, order, spacing — untouched.
    Also updates os.environ, so a saved key takes effect without a restart."""
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")

    remaining = dict(values)
    # The LAST occurrence of a key is the one every reader sees — `read_env` and the
    # dotenv load under `config` both let a later line override an earlier one. This
    # rewrote the FIRST, so in a hand-edited file carrying a key twice the Save
    # reported success and the next launch read the stale duplicate below it. The
    # shadowed line is left where it is: it is dead to every reader, and this function
    # promises to keep what it does not own.
    at = {}
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        m = _LINE.match(line)
        if m and m.group(1) in remaining:
            at[m.group(1)] = i
    for key, i in at.items():
        comment = _comment_of(_LINE.match(lines[i]).group(2))
        lines[i] = f"{key}={_format(remaining.pop(key))}"
        if comment:
            lines[i] += f"  {comment}"

    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"{k}={_format(v)}" for k, v in remaining.items()]

    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    # plain-text API keys: at least keep the file off other accounts on the machine
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass                        # a filesystem without unix modes must not break saving

    for k, v in values.items():
        os.environ[k] = "" if v is None else str(v)


def mask(value: str) -> str:
    """Enough of a secret to recognise it, not enough to use it."""
    v = value or ""
    if not v:
        return ""
    return f"{v[:4]}…{v[-4:]}" if len(v) >= 12 else "…"
