"""How big the window opens.

Size only. POSITION IS DELIBERATELY NOT SET: every pywebview backend centres the window
itself when `x` and `y` are both omitted (cocoa `center()`, WinForms `CenterScreen`, gtk
computes it), and passing coordinates switches that off. A first attempt did pass them
and the window landed off-centre — the y was computed from a top-left origin while Cocoa
places frames from the bottom-left. Let the platform do it.
"""

MIN_SIZE = (1024, 720)      # the app's own minimum; below this the picker starts wrapping
MAX_SIZE = (1600, 1040)     # past this the content columns just grow whitespace
FILL = 0.88                 # of the screen, leaving the dock and menu bar visible


def geometry(screen_w, screen_h):
    """-> (width, height). Never smaller than MIN_SIZE, never larger than MAX_SIZE."""
    try:
        sw, sh = int(screen_w), int(screen_h)
    except (TypeError, ValueError):
        sw = sh = 0
    if sw <= 0 or sh <= 0:
        sw, sh = MIN_SIZE

    return (min(MAX_SIZE[0], max(MIN_SIZE[0], int(sw * FILL))),
            min(MAX_SIZE[1], max(MIN_SIZE[1], int(sh * FILL))))
