import cv2
import numpy as np
from typing import Optional, List, Dict, Tuple

from .camera import list_available_cameras, open_camera
from .devices import get_camera_names


# Key codes helpers
ESC = 27
ENTER = 13
SPACE = 32
UP_KEYS = {2490368, 82}   # Windows arrow up, keypad code; 82 sometimes from older backends
DOWN_KEYS = {2621440, 84} # Windows arrow down; 84 sometimes from older backends


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
    inst = "Arrow Up/Down to select  •  Enter/Space to confirm  •  R to rescan  •  Esc to exit"
    cv2.putText(canvas, inst, (60, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1, cv2.LINE_AA)
    y += 20

    # Items list (left area)
    top = y + 20
    line_h = 36
    # Reserve right area for preview (~40% width)
    preview_w = int(w * 0.4)
    list_width = w - preview_w - 100  # 60 left margin + 40 padding
    max_visible = max(1, (h - top - 40) // line_h)

    # Draw a faint separator for preview area
    x_sep = w - preview_w - 40
    cv2.line(canvas, (x_sep, 40), (x_sep, h - 40), (60, 60, 60), 1, cv2.LINE_AA)

    start = max(0, min(selected - max_visible // 2, max(0, len(items) - max_visible)))
    end = min(len(items), start + max_visible)

    for i in range(start, end):
        text = items[i]
        y_i = top + (i - start) * line_h
        if i == selected:
            cv2.rectangle(canvas, (50, y_i - 24), (x_sep - 10, y_i + 12), (40, 80, 160), thickness=-1)
            color = (255, 255, 255)
            marker = ">"
        else:
            color = (210, 210, 210)
            marker = "  "
        # Clip text to left area width
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


def _render_preview(
    canvas: np.ndarray,
    frame: Optional[np.ndarray],
    label: str,
) -> None:
    h, w = canvas.shape[:2]
    pad = 40
    area_w = int(w * 0.38)
    area_h = int(h * 0.38)
    x0 = w - area_w - pad
    y0 = pad
    x1 = w - pad
    y1 = y0 + area_h

    # Background panel
    cv2.rectangle(canvas, (x0, y0), (x1, y1), (32, 32, 32), thickness=-1)
    cv2.rectangle(canvas, (x0, y0), (x1, y1), (80, 80, 80), thickness=1)
    cv2.putText(canvas, "Preview", (x0, y0 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2, cv2.LINE_AA)

    if frame is not None and frame.size > 0:
        fh, fw = frame.shape[:2]
        # Fit frame into area with letterboxing
        scale = min((area_w - 4) / fw, (area_h - 4) / fh)
        new_w = max(1, int(fw * scale))
        new_h = max(1, int(fh * scale))
        resized = cv2.resize(frame, (new_w, new_h))
        # Center
        xx = x0 + (area_w - new_w) // 2
        yy = y0 + (area_h - new_h) // 2
        canvas[yy:yy+new_h, xx:xx+new_w] = resized
    else:
        cv2.putText(canvas, "No preview", (x0 + 20, y0 + area_h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (180, 180, 180), 2, cv2.LINE_AA)

    # Label under preview
    cv2.putText(canvas, label, (x0, y1 + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1, cv2.LINE_AA)


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
    preview_cap: Optional[cv2.VideoCapture] = None
    preview_idx: Optional[int] = None

    def scan() -> Tuple[List[Dict], List[str], List[str]]:
        cand = list_available_cameras(max_index=max_index, width=width, height=height)
        dev_names = get_camera_names()
        items = _format_items(cand, dev_names)
        return cand, dev_names, items

    candidates, dev_names, items = scan()

    try:
        while True:
            # Update preview capture if needed
            preview_frame = None
            preview_label = ""
            if candidates:
                target_idx = int(candidates[selected]["index"]) if selected < len(candidates) else None
                preview_label = items[selected] if selected < len(items) else ""
                if target_idx is not None:
                    if preview_idx != target_idx or (preview_cap is not None and not preview_cap.isOpened()):
                        # Reopen preview for new target
                        if preview_cap is not None:
                            try:
                                preview_cap.release()
                            except Exception:
                                pass
                            preview_cap = None
                        preview_cap = open_camera(target_idx, width=width, height=height)
                        preview_idx = target_idx
                    if preview_cap is not None and preview_cap.isOpened():
                        ok, f = preview_cap.read()
                        if ok and f is not None:
                            preview_frame = f

            # Render UI
            _render_menu(
                canvas,
                title="Select Camera",
                subtitle="Choose the input camera for the game.",
                items=items,
                selected=selected if items else 0,
            )
            _render_preview(canvas, preview_frame, preview_label)

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
            if key in UP_KEYS:
                if items:
                    selected = (selected - 1) % len(items)
                continue
            if key in DOWN_KEYS:
                if items:
                    selected = (selected + 1) % len(items)
                continue
            if key in (ord('r'), ord('R')):
                # Release current preview before rescanning
                if preview_cap is not None:
                    try:
                        preview_cap.release()
                    except Exception:
                        pass
                    preview_cap = None
                    preview_idx = None
                candidates, dev_names, items = scan()
                if selected >= len(items):
                    selected = max(0, len(items) - 1)
                continue
    finally:
        try:
            if preview_cap is not None:
                preview_cap.release()
        except Exception:
            pass
        try:
            cv2.destroyWindow(window_name)
        except Exception:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

    return None
