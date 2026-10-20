"""LabelGuard - AI pre-flight checker for packaging artwork."""
import os
import sys


def _preload_windows_cpp_runtime():
    """Work around a Windows crash in onnxruntime (used by OCR and PyMuPDF).

    Anaconda's Python ships an old Microsoft C++ runtime (msvcp140.dll 14.29);
    current onnxruntime needs a newer one and crashes with an access violation
    when the old copy is picked up. Loading the system's (newer) runtime first
    makes every later import use it. No effect on other platforms.
    """
    if sys.platform != "win32":
        return
    import ctypes
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    for dll in ("msvcp140.dll", "msvcp140_1.dll", "vcruntime140_1.dll"):
        path = os.path.join(system32, dll)
        if os.path.exists(path):
            try:
                ctypes.WinDLL(path)
            except OSError:
                pass


_preload_windows_cpp_runtime()
