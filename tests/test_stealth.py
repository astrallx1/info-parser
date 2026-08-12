from topicparser.collectors.stealth import STEALTH_JS, apply_stealth


class FakeCtx:
    def __init__(self):
        self.scripts = []
    def add_init_script(self, s):
        self.scripts.append(s)


def test_apply_stealth_adds_one_init_script():
    ctx = FakeCtx()
    apply_stealth(ctx)
    assert len(ctx.scripts) == 1


def test_stealth_js_patches_webdriver():
    # the biggest bot tell must be neutralized
    assert "webdriver" in STEALTH_JS


def test_stealth_js_patches_more_fingerprints():
    for tell in ("plugins", "languages", "chrome"):
        assert tell in STEALTH_JS
