"""How big the window opens, and who decides where.

It was hardcoded to 1280x860, so on the owner's 1710x1107 screen it opened at a size
unrelated to the display. The size follows the screen now. The POSITION is not ours to
set: every pywebview backend centres the window when x and y are omitted, and passing
them turns that off — which is exactly how the first attempt at this made the window
land off-centre.
"""
import inspect

from topicparser.window import MAX_SIZE, MIN_SIZE, geometry


def test_it_fills_most_of_the_screen():
    w, h = geometry(1710, 1107)

    assert 0.8 < w / 1710 < 0.95
    assert 0.8 < h / 1107 < 0.95


def test_a_huge_display_does_not_get_a_huge_window():
    """On a 5K panel 88% is unusable — the content columns are capped anyway."""
    assert geometry(5120, 2880) == MAX_SIZE


def test_a_small_display_never_goes_under_the_minimum():
    assert geometry(1024, 700) == MIN_SIZE


def test_nonsense_screen_metrics_fall_back_instead_of_crashing():
    for bad in ((0, 0), (-1, -1), (None, None)):
        assert geometry(*bad) == MIN_SIZE


def test_geometry_returns_a_size_and_nothing_else():
    """A regression guard: returning x/y again would mean someone passed them to
    create_window, and the platform would stop centring."""
    assert len(geometry(1710, 1107)) == 2


def test_main_does_not_pass_a_window_position():
    """The centring lives in pywebview and only runs when x and y are both absent."""
    import main

    source = inspect.getsource(main.main)
    body = source[source.index("create_window"):source.index("min_size")]
    assert "x=" not in body and "y=" not in body
