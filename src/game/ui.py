import cv2
import numpy as np
from typing import Optional, List, Dict, Tuple

from .camera import list_available_cameras
from .devices import get_camera_names


# Key codes helpers
ESC = 27
ENTER = 13
SPACE = 32
UP_KEYS = {2490368, 82}   # Windows arrow up, keypad code; 82 sometimes from older backends
DOWN_KEYS = {2621440, 84} # Windows arrow down; 84 sometimes from older backends
ALT_UP = {ord('k'), ord('K'), ord('w'), ord('W')}
ALT_DOWN = {ord('j'), ord('J'), ord('s'), ord('S')}


def _render_menu(
    canvas: np.ndarray,
    title: str,
    subtitle: str,
    items: List[str],
    selected: int,
) -> None:
    h, w = canvas.shape[:2]
    canvas[:] = (16, 16, 16)

    # Title
    y = 60
    cv2.putText(canvas, title, (60, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (240, 240, 240), 2, cv2.LINE_AA)
    y += 40
    cv2.putText(canvas, subtitle, (60, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1, cv2.LINE_AA)
    y += 30

    # Instructions
    inst = "Arrow Up/Down (or W/S, J/K) to select  •  Enter/Space to confirm  •  R to rescan  •  Esc to exit"
    cv2.putText(canvas, inst, (60, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1, cv2.LINE_AA)
    y += 20

    # Items list
    top = y + 20
    line_h = 36
    max_visible = max(1, (h - top - 40) // line_h)
    # Scroll window to keep selected visible
    start = max(0, min(selected - max_visible // 2, max(0, len(items) - max_visible)))
    end = min(len(items), start + max_visible)

    for i in range(start, end):
        text = items[i]
        y_i = top + (i - start) * line_h
        if i == selected:
            cv2.rectangle(canvas, (50, y_i - 24), (w - 50, y_i + 12), (40, 80, 160), thickness=-1)
            color = (255, 255, 255)
            marker = ">"
        else:
            color = (210, 210, 210)
            marker = "  "
        cv2.putText(canvas, f"{marker} {text}", (60, y_i), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2, cv2.LINE_AA)

    if len(items) == 0:
        cv2.putText(
            canvas,
            "No cameras detected. Press R to rescan or Esc to exit.",
            (60, top),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (210, 210, 210),
            2,
            cv2.LINE_AA,
        )


def _format_items(candidates: List[Dict], names: List[str]) -> List[str]:
    lines: List[str] = []
    for i, info in enumerate(candidates):
        res = info.get("resolution") or ("?", "?")
        label = f" - {names[i]}" if i < len(names) else ""
        lines.append(
            f"[{i}] device_index={info['index']} backend={info['backend']} resolution={res[0]}x{res[1]}{label}"
        )
    return lines


def select_camera_gui(
    max_index: int = 5,
    width: int = 1280,
    height: int = 720,
    window_name: str = "Pose Game - Select Camera",
) -> Optional[int]:
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    selected = 0

    def scan() -> Tuple[List[Dict], List[str], List[str]]:
        cand = list_available_cameras(max_index=max_index, width=width, height=height)
        dev_names = get_camera_names()
        items = _format_items(cand, dev_names)
        return cand, dev_names, items

    candidates, dev_names, items = scan()

    try:
        while True:
            _render_menu(
                canvas,
                title="Select Camera",
                subtitle="Choose the input camera for the game.",
                items=items,
                selected=selected if items else 0,
            )
            cv2.imshow(window_name, canvas)
            key = cv2.waitKey(30) & 0xFFFFFFFF

            if key == 0xFFFFFFFF:
                continue
            if key == ESC:
                return None
            if key in (ENTER, SPACE):
                if candidates and 0 <= selected < len(candidates):
                    return int(candidates[selected]["index"])
                else:
                    # nothing to select; rescan
                    candidates, dev_names, items = scan()
                    continue
            if key in UP_KEYS or key in ALT_UP:
                if items:
                    selected = (selected - 1) % len(items)
                continue
            if key in DOWN_KEYS or key in ALT_DOWN:
                if items:
                    selected = (selected + 1) % len(items)
                continue
            if key in (ord('r'), ord('R')):
                candidates, dev_names, items = scan()
                if selected >= len(items):
                    selected = max(0, len(items) - 1)
                continue
    finally:
        try:
            cv2.destroyWindow(window_name)
        except Exception:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

    return None
