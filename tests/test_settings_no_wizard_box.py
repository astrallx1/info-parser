"""Settings does not offer to re-run the setup guide.

Every step the guide asks for — the GitHub token, the OpenAI key, the X session — has
its own field a few centimetres higher on the SAME screen, so the box was a second door
into the same room. The guide itself stays: it opens by itself on a first launch, which
is the one moment those fields do not exist yet.
"""
import pathlib


def test_the_settings_screen_has_no_rerun_guide_box():
    ui = pathlib.Path("topicparser/ui/index.html").read_text(encoding="utf-8")
    assert "set-wizard" not in ui
    assert "settings.rerun_wizard" not in ui
    assert "settings.guide_help" not in ui


def test_the_first_run_guide_itself_is_still_there():
    ui = pathlib.Path("topicparser/ui/index.html").read_text(encoding="utf-8")
    assert "function openWizard(" in ui, "the guide still has to open on a first launch"
    assert "setup_state" in ui
