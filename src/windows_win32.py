"""Read other windows' geometry on Windows (ctypes/Win32), so the pet can
perch on and be contained by them — the Windows equivalent of the KWin/D-Bus
geometry feed in `pet.py`.

Win32 has nothing like KWin scripting's push-on-change signals, so this is
polled on a timer instead of pushed. EnumWindows already returns windows in
current, correct Z-order every call, so (unlike the KWin feed) no
just-activated-window workaround is needed here.

Produces the same wire format the KWin feed uses (`windows.parse_kwin_dump`),
so it plugs into the existing, already-tested perch/contain pipeline
unchanged: `id;class;x,y,w,h;pid|id;class;x,y,w,h;pid|...`, bottom-to-top.
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
dwmapi = ctypes.windll.dwmapi if hasattr(ctypes, "windll") else None
kernel32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
SW_RESTORE = 9
TH32CS_SNAPPROCESS = 0x00000002
_WNDENUMPROC = (ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                if hasattr(ctypes, "windll") else None)   # WINFUNCTYPE is Windows-only


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


# Without argtypes/restype, ctypes assumes every call returns a 32-bit c_int
# and marshals HWND/HANDLE args as plain ints — Microsoft documents that both
# stay within the 32-bit range even on 64-bit Windows, so this has been
# harmless in practice, but declaring the real types is what makes that
# reliable rather than incidental (and gives ctypes correct argument
# marshalling instead of guessing from the Python value passed in).
if user32 is not None:
    user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL

if dwmapi is not None:
    dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long   # HRESULT

# CreateToolhelp32Snapshot returns a real kernel HANDLE, not a small window
# id — give it its own correctly-sized invalid-handle sentinel rather than
# reusing the `== -1` check that only happened to work by accident under the
# untyped c_int default.
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

if kernel32 is not None:
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32)]
    kernel32.Process32First.restype = wintypes.BOOL
    kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32)]
    kernel32.Process32Next.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def _is_cloaked(hwnd):
    """True if DWM is hiding this window despite IsWindowVisible() saying True.
    Modern Windows leaves UWP/shell surfaces (Settings, input UI, etc.) around
    in this cloaked state on other virtual desktops/suspended — visible-looking
    rects that aren't actually drawn, which the pet would otherwise perch on or
    hide behind as if they were real."""
    if dwmapi is None:
        return False
    cloaked = ctypes.c_int(0)
    hr = dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return hr == 0 and cloaked.value != 0


def _visible_rect(hwnd):
    """GetWindowRect on Win10/11 includes an invisible resize-border margin for
    many apps (observed ~7-8px on Chrome/Electron and Windows Terminal) — the
    reported box is bigger than what's actually drawn on screen. That's fine
    for "contain" (just a loose bounding box) but throws off "perch", which
    needs the pet's feet to land exactly on the visible top edge. DWM's
    extended-frame-bounds attribute gives the true visible rect; fall back to
    GetWindowRect if DWM has nothing (composition off, exotic window types)."""
    rect = wintypes.RECT()
    if dwmapi is not None:
        hr = dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect))
        if hr == 0:
            return rect
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return rect
    return None


def _enum_windows(exclude_hwnd=None):
    """Visible, non-minimized top-level windows, topmost-first (raw Win32 order)."""
    out = []

    def _cb(hwnd, _lparam):
        if exclude_hwnd is not None and hwnd == exclude_hwnd:
            return True
        # Cheap, local user32 checks first — DwmGetWindowAttribute is a call
        # into dwm.exe, and every top-level window on the system (including
        # dozens of invisible/helper ones) reaches this callback each poll,
        # so paying for DWM only after the free filters narrows it down a lot.
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        if user32.GetWindowTextLengthW(hwnd) == 0:
            return True                  # no title -> background/helper window
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex_style & WS_EX_TOOLWINDOW:
            return True
        if _is_cloaked(hwnd):
            return True
        rect = _visible_rect(hwnd)
        if rect is None:
            return True
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out.append((hwnd, buf.value.lower(), rect.left, rect.top, w, h, pid.value))
        return True

    user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return out


def dump(exclude_hwnd=None):
    """Current windows as a KWin-feed-format string (bottom-to-top stacking)."""
    if user32 is None:
        return ""
    rows = _enum_windows(exclude_hwnd)
    rows.reverse()   # EnumWindows is topmost-first; the feed format wants bottom->top
    return "|".join(
        "{};{};{},{},{},{};{}".format(hwnd, cls, x, y, w, h, pid)
        for hwnd, cls, x, y, w, h, pid in rows
    )


def _proc_snapshot():
    """[(pid, name, ppid), ...] for every running process, via one Toolhelp
    snapshot — the Windows equivalent of iterating /proc on Linux."""
    rows = []
    if kernel32 is None:
        return rows
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return rows
    try:
        entry = _PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        ok = kernel32.Process32First(snap, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.decode(errors="replace").lower()
            rows.append((entry.th32ProcessID, name, entry.th32ParentProcessID))
            ok = kernel32.Process32Next(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return rows


def proc_table():
    """{pid: (name, ppid)} for every running process. Used to walk up from a
    transient hook shell to the real `claude` process by name — the Windows
    counterpart of reading /proc/<pid>/stat's comm+ppid (see
    bin/claude-pet-hook's resolve_claude_pid/_proc_info)."""
    return {pid: (name, ppid) for pid, name, ppid in _proc_snapshot()}


def proc_ancestors(pid, max_hops=40):
    """Set of pids from `pid` up to the top, via a Toolhelp process snapshot —
    the Windows equivalent of walking /proc/<pid>/stat's ppid chain on Linux.
    The terminal/IDE window's owning pid is one of these, so matching it to a
    window pid finds the host window for click-to-focus."""
    acc = set()
    try:
        cur = int(pid)
    except (TypeError, ValueError):
        return acc
    parent = {p: pp for p, _, pp in _proc_snapshot()}
    if not parent:
        return acc
    while cur > 1 and cur not in acc and len(acc) < max_hops:
        acc.add(cur)
        nxt = parent.get(cur)
        if not nxt:
            break
        cur = nxt
    return acc


def activate_hwnd(hwnd):
    """Bring `hwnd` to the foreground (Windows' click-to-focus). Windows only
    lets the process owning the current foreground window change focus, so we
    borrow that permission by attaching our input thread to both the current
    foreground window's and the target's — the standard SetForegroundWindow
    workaround."""
    if user32 is None or kernel32 is None or not hwnd:
        return
    try:
        hwnd = int(hwnd)
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        fg = user32.GetForegroundWindow()
        cur_thread = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        attached_fg = attached_target = False
        if fg_thread and fg_thread != cur_thread:
            attached_fg = bool(user32.AttachThreadInput(cur_thread, fg_thread, True))
        if target_thread and target_thread != cur_thread:
            attached_target = bool(user32.AttachThreadInput(cur_thread, target_thread, True))
        try:
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
        finally:
            if attached_fg:
                user32.AttachThreadInput(cur_thread, fg_thread, False)
            if attached_target:
                user32.AttachThreadInput(cur_thread, target_thread, False)
    except Exception:
        pass
