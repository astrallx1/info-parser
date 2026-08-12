"""Automation-fingerprint patches applied to a Playwright context before page
loads, so X's bot detection sees a normal Chrome instead of a controlled one.

Injected via `context.add_init_script` so it runs in every page/frame at document
start, before site JS reads these properties.
"""

# Runs at document-start in every frame. Neutralizes the loudest automation tells.
STEALTH_JS = r"""
(() => {
  // 1. navigator.webdriver -> undefined (Playwright sets it true)
  try { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); } catch (e) {}

  // 2. plugins / mimeTypes -> non-empty like a real Chrome
  try {
    Object.defineProperty(navigator, 'plugins', {
      get: () => [1, 2, 3, 4, 5].map(i => ({name: 'Plugin ' + i}))
    });
  } catch (e) {}

  // 3. languages -> realistic
  try { Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']}); } catch (e) {}

  // 4. window.chrome -> present (headless lacks it)
  try { if (!window.chrome) { window.chrome = {runtime: {}}; } } catch (e) {}

  // 5. permissions.query for notifications behaves like a real browser
  try {
    const orig = window.navigator.permissions && window.navigator.permissions.query;
    if (orig) {
      window.navigator.permissions.query = (p) =>
        p && p.name === 'notifications'
          ? Promise.resolve({state: Notification.permission})
          : orig(p);
    }
  } catch (e) {}

  // 6. WebGL vendor/renderer -> real GPU strings (headless reports SwiftShader)
  try {
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (p) {
      if (p === 37445) return 'Intel Inc.';            // UNMASKED_VENDOR_WEBGL
      if (p === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
      return getParam.call(this, p);
    };
  } catch (e) {}
})();
"""


def apply_stealth(context) -> None:
    """Register the stealth init script on a Playwright browser context."""
    context.add_init_script(STEALTH_JS)
