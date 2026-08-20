"""Bundled app font (Itim — supports Thai) loaded privately, no system install needed."""
import sys
from pathlib import Path

APP_FONT = "Itim"

# When frozen by PyInstaller, bundled data lives under sys._MEIPASS, not next to this file.
_BASE_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
_FONTS_DIR = _BASE_DIR / "assets" / "fonts"


def load_bundled_fonts():
    """Register bundled .ttf fonts for this process only. Must run before any Tk widgets are built."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        FR_PRIVATE = 0x10
        gdi32 = ctypes.windll.gdi32
        gdi32.AddFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
        gdi32.AddFontResourceExW.restype = ctypes.c_int
        for f in _FONTS_DIR.glob("*.ttf"):
            gdi32.AddFontResourceExW(str(f), FR_PRIVATE, None)
    except Exception:
        pass
