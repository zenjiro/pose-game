import platform
import subprocess
from typing import List, Optional


def _run_powershell(cmd: str, timeout: float = 3.0) -> Optional[str]:
    """Run a PowerShell command and return stdout as text, or None on failure."""
    shell = "powershell"
    if platform.system() != "Windows":
        return None
    try:
        proc = subprocess.run(
            [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout
    except Exception:
        return None


def get_windows_camera_names() -> List[str]:
    """
    Best-effort retrieval of camera device names on Windows via CIM/WMI.
    Note: The order may not map 1:1 to OpenCV device indices across backends.
    """
    if platform.system() != "Windows":
        return []

    # Try Camera class first (Windows 10+ often reports integrated cameras here)
    ps_cmds = [
        "Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPClass -eq 'Camera' } | Select-Object -ExpandProperty Name",
        # Fallback: USB Video Class devices
        "Get-CimInstance Win32_PnPEntity | Where-Object { $_.Service -eq 'usbvideo' } | Select-Object -ExpandProperty Name",
        # Fallback: generic image-related names
        "Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match 'Camera|Webcam|USB Video|Integrated' } | Select-Object -ExpandProperty Name",
    ]

    seen = []
    for cmd in ps_cmds:
        out = _run_powershell(cmd)
        if not out:
            continue
        for line in out.splitlines():
            name = line.strip()
            if name and name not in seen:
                seen.append(name)
    return seen


def get_camera_names() -> List[str]:
    """Return a list of human-friendly camera names if available, else empty list."""
    if platform.system() == "Windows":
        return get_windows_camera_names()
    # TODO: Add macOS/Linux implementations (e.g., ioreg/v4l2-ctl) if needed.
    return []
