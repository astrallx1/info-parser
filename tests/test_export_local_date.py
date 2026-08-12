from topicparser import export, i18n


def test_header_uses_the_local_day_not_utc(tmp_path, monkeypatch):
    """The header dates the export. It used UTC, so for the first hours of a local
    day (UTC+2/+3 here) the file claimed yesterday. It must follow the owner's clock."""
    monkeypatch.setattr(export, "_local_today", lambda: "2026-08-04")
    out = tmp_path / "t.md"
    export.write_markdown([], str(out))
    assert "# " + i18n.t("md.title", date="2026-08-04") in out.read_text(encoding="utf-8")


def test_explicit_date_still_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "_local_today", lambda: "2026-08-04")
    out = tmp_path / "t.md"
    export.write_markdown([], str(out), date="2026-01-09")
    assert "# " + i18n.t("md.title", date="2026-01-09") in out.read_text(encoding="utf-8")
