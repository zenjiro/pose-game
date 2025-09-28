"""
Minimal Arcade sample to draw Japanese text, with diagnostics.

Usage:
  uv run python scripts/arcade_jp_text_sample.py
  uv run python scripts/arcade_jp_text_sample.py --font "C:\\Windows\\Fonts\\meiryo.ttc"
  uv run python scripts/arcade_jp_text_sample.py --font "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
  uv run python scripts/arcade_jp_text_sample.py --font "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"

Notes:
- You can pass either a font file path or a font family name via --font.
- If --font is omitted, the script tries several common JP fonts by family name.
- Add --diagnose-only to print environment/font info without opening a window.
- Add --render-seconds N to auto-close the window after N seconds (useful for CI or quick checks).
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
from typing import Sequence

import arcade
import pyglet

SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
SCREEN_TITLE = "日本語描画テスト (Arcade)"


def _default_font_candidates() -> list[str]:
    """Return a list of font family names commonly present across OSes.

    Arcade/pyglet will try them in order. You may also pass a font path via --font.
    """
    return [
        # Windows
        "Meiryo",
        "MS Gothic",
        "Yu Gothic",
        # macOS (Hiragino)
        "Hiragino Sans W6",
        "Hiragino Sans",
        "Hiragino Kaku Gothic ProN W6",
        # Linux (Noto CJK, IPA, Takao, VL)
        "Noto Sans CJK JP",
        "Noto Sans JP",
        "IPAGothic",
        "IPAexGothic",
        "TakaoGothic",
        "VL Gothic",
    ]


def _print_diagnostics(font_candidates: Sequence[str]) -> None:
    print("=== Environment ===")
    print(f"Arcade: {getattr(arcade, '__version__', 'unknown')}")
    print(f"Pyglet: {getattr(pyglet, 'version', 'unknown')}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Platform: {platform.platform()}")
    print()

    # Check font availability
    print("=== Font candidates ===")
    from pyglet.font import have_font

    for name in font_candidates:
        if os.path.isfile(name):
            # Try registering the font file so pyglet can use it by family name.
            try:
                arcade.load_font(name)
                print(f"file: {name} -> load OK")
            except Exception as e:
                print(f"file: {name} -> load FAILED: {e}")
        else:
            available = have_font(name)
            print(f"family: {name} -> {'found' if available else 'NOT found'}")
    print()


class MyGame(arcade.Window):
    def __init__(self, font_candidates: Sequence[str] | str | None = None):
        super().__init__(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE, update_rate=1 / 60)
        arcade.set_background_color(arcade.color.LIGHT_GRAY)

        # font_name in Arcade can be a single string or a list of candidates.
        # If a list is provided, Arcade will try them in order.
        if font_candidates is None:
            # Arcade 3.3+ expects a string or a tuple of strings (not a list).
            self.font_name: tuple[str, ...] | str = tuple(_default_font_candidates())
        else:
            # Accept either a single family/file name or a sequence of names.
            self.font_name = font_candidates if isinstance(font_candidates, str) else tuple(font_candidates)

        self.lines = [
            "こんにちは、世界！",
            "各種フォントで日本語を描画しています。",
        ]
        self.font_size = 36
        self.leading = int(self.font_size * 1.25)

    def on_draw(self):
        self.clear()

        # Draw the lines with manual line spacing to avoid multiline quirks.
        start_x = 50
        start_y = 360
        color = arcade.color.BLACK
        for i, line in enumerate(self.lines):
            y = start_y - i * self.leading
            arcade.draw_text(
                line,
                start_x,
                y,
                color,
                font_size=self.font_size,
                font_name=self.font_name,
            )

        # Display which fonts are being attempted
        arcade.draw_text(
            f"font_name: {self.font_name}",
            50,
            100,
            arcade.color.DARK_BLUE,
            font_size=16,
            font_name=self.font_name,
        )


def main():
    parser = argparse.ArgumentParser(description="Arcade JP text rendering sample")
    parser.add_argument(
        "--font",
        dest="font",
        help=(
            "Font family name or font file path to try first. If omitted, a set of common JP fonts will be tried."
        ),
    )
    parser.add_argument(
        "--diagnose-only",
        action="store_true",
        help="Print environment/font info and exit without opening a window.",
    )
    parser.add_argument(
        "--render-seconds",
        type=float,
        default=0.0,
        help="Open a window, render, and auto-close after N seconds (0 to keep open).",
    )
    args = parser.parse_args()

    # If a specific font is provided, try it first, then fall back to defaults.
    if args.font:
        font_candidates: Sequence[str] = [args.font] + _default_font_candidates()
    else:
        font_candidates = _default_font_candidates()

    # Print diagnostics
    _print_diagnostics(font_candidates)

    if args.diagnose_only:
        return

    try:
        window = MyGame(font_candidates=font_candidates)
        if args.render_seconds > 0:
            from pyglet import clock

            clock.schedule_once(lambda dt: window.close(), args.render_seconds)
        arcade.run()
    except Exception:
        # If something goes wrong, print a full stack trace for sharing.
        import traceback

        print("\n=== Exception ===")
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
