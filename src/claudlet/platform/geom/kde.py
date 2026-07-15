"""KDE window-geometry feed for the pet's perch/occlusion pipeline.

The Linux equivalent of `win32.py` / `macos.py`, but PUSH-based instead of
polled: KWin scripting can emit on every window geometry change, so instead of
polling a window list on a timer we register a D-Bus object and load a
persistent KWin script that calls back into it (`push`) whenever something
moves, (un)minimizes, is added/removed, or is raised.

Produces the same wire format the other backends do (`geom.parse_dump`):
`id;class;x,y,w,h;pid|id;class;x,y,w,h;pid|...`, bottom-to-top, so it plugs
into the already-tested perch/contain pipeline unchanged.

Contract (fits the existing `pet._on_geom` seam):
    available()                     -> bool   True on KDE with a reachable
                                               `qdbus6 org.kde.KWin /Scripting`.
    start(on_dump, session_id,
          on_cursor=None)           -> handle load the KWin geometry script +
                                               register the D-Bus sink so each
                                               pushed dump calls on_dump(text).
    stop(handle)                    -> None   unload the geometry script.

The D-Bus object registered here is SHARED with pet.py's cursor feed: the
cursor KWin script (which stays in pet.py) pushes to the same D-Bus service
name and path, dispatching to this object's `cursor` slot. That is why the
handle exposes `.dbus_name` (the cursor feed reads it to address its pushes)
and why `start` accepts `on_cursor` (so this object can route those pushes back
to pet). The geometry script's own self-exclusion is by resourceClass
"claudlet" (baked into the JS below), independent of the window title.
"""
import os
import re
import subprocess
import sys
import tempfile

try:
    from PyQt6.QtDBus import QDBusConnection   # KDE window integration (Linux)
except Exception:                              # no QtDBus on some Qt builds
    QDBusConnection = None
from PyQt6.QtCore import QObject, pyqtSlot

from claudlet.platform.qdbus import qdbus_bin


class _GeomReceiver(QObject):
    """D-Bus object the KWin scripts push to. `push` carries a window-geometry
    dump (geometry feed); `cursor` carries the global cursor position (pet.py's
    cursor feed reuses this same object). Both slots are exported via
    ExportAllSlots when registered."""
    def __init__(self, on_dump, on_cursor=None):
        super().__init__()
        self._on_dump = on_dump
        self._on_cursor = on_cursor

    @pyqtSlot(str)
    def push(self, dump):
        self._on_dump(dump)

    @pyqtSlot(str)
    def cursor(self, xy):
        if self._on_cursor is not None:
            self._on_cursor(xy)


class _Handle:
    """Teardown state for a started KDE geometry feed. `dbus_name` is read by
    pet.py's cursor feed to address its own pushes at the same D-Bus object."""
    def __init__(self, bus, dbus_name, receiver, plugin, script_id):
        self.bus = bus
        self.dbus_name = dbus_name
        self.receiver = receiver
        self.plugin = plugin
        self.script_id = script_id


def available():
    """True on KDE with a reachable `qdbus6 org.kde.KWin /Scripting` and QtDBus
    present. Any probe failure -> False (feed just stays off)."""
    if os.name == "nt" or sys.platform == "darwin":
        return False
    if QDBusConnection is None:
        return False
    try:
        r = subprocess.run(
            [qdbus_bin(), "org.kde.KWin", "/Scripting"],
            timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except Exception:
        return False


def start(on_dump, session_id, on_cursor=None):
    """Register the D-Bus sink and load the persistent KWin geometry script so
    each pushed dump calls on_dump(text). `on_cursor`, if given, receives cursor
    pushes routed through the same (shared) D-Bus object. Returns a handle for
    stop(), or None if the D-Bus service could not be registered."""
    if QDBusConnection is None:
        return None
    try:
        safe = re.sub(r"[^A-Za-z0-9_]", "_", str(session_id))
        dbus_name = "org.claudlet.geom_" + safe
        receiver = _GeomReceiver(on_dump, on_cursor)
        bus = QDBusConnection.sessionBus()
        if not bus.registerService(dbus_name):
            return None
        bus.registerObject("/", receiver,
                           QDBusConnection.RegisterOption.ExportAllSlots)
        plugin, script_id = _start_geom_script(dbus_name, safe)
        return _Handle(bus, dbus_name, receiver, plugin, script_id)
    except Exception:
        return None


def _start_geom_script(dbus_name, safe):
    svc = dbus_name
    js = (
        'var SVC="' + svc + '";'
        # only windows on the CURRENT virtual desktop count (a perched pet is
        # sticky/all-desktops, so a window that leaves the desktop must drop
        # out of the feed -> pet falls to the desktop floor instead of
        # hovering where the vanished window was).
        'function _onDesk(c){'
        '  if(c.onAllDesktops)return true;'
        '  try{'
        '    if(c.desktops&&c.desktops.length!==undefined){var cur=workspace.currentDesktop;'
        '      for(var k=0;k<c.desktops.length;k++){if(c.desktops[k]===cur)return true;}'
        '      return false;}'
        '    if(typeof c.desktop==="number")'
        '      return c.desktop<0||c.desktop===workspace.currentDesktop;'
        '  }catch(e){}'
        '  return true;}'                             # unknown API -> don't filter
        'function _dump(top){'
        # stackingOrder is bottom->top, so geom.window_at's "last match
        # wins" correctly picks the TOPMOST window under the pet.
        '  var ws=(typeof workspace.stackingOrder!=="undefined"&&workspace.stackingOrder)'
        '    ?workspace.stackingOrder'
        '    :((typeof workspace.windowList==="function")'
        '      ?workspace.windowList():workspace.clientList());'
        '  var ent=[];'
        '  for(var i=0;i<ws.length;i++){var c=ws[i];var g=c.frameGeometry;'
        '    if(g&&!c.minimized&&!c.hidden&&_onDesk(c))'   # visible, on this desktop
        '      ent.push({id:(""+c.internalId),'
        '        s:c.internalId+";"+(c.resourceClass||"")+";"'
        '        +g.x+","+g.y+","+g.width+","+g.height+";"+(c.pid||0)});}'
        # workspace.stackingOrder lags a raise in this KWin (it settles AFTER
        # windowActivated fires), so a just-activated window would still look
        # buried for one click. We KNOW it is now topmost -> force it last.
        '  if(top){var tid=""+top.internalId;'
        '    for(var j=0;j<ent.length;j++){if(ent[j].id===tid){'
        '      ent.push(ent.splice(j,1)[0]);break;}}}'
        '  var o=[];for(var k=0;k<ent.length;k++)o.push(ent[k].s);'
        '  callDBus(SVC,"/","","push",o.join("|"));'
        '}'
        'function _hook(c){if(!c)return;'
        '  if((""+(c.resourceClass||"")).toLowerCase().indexOf("claudlet")>=0)'
        '    return;'                                  # never react to our own window
        '  if(c.frameGeometryChanged)c.frameGeometryChanged.connect(_dump);'
        '  if(c.minimizedChanged)c.minimizedChanged.connect(_dump);}'  # refresh on (un)minimize
        'var _w=(typeof workspace.windowList==="function")'
        '  ?workspace.windowList():workspace.clientList();'
        'for(var i=0;i<_w.length;i++)_hook(_w[i]);'
        'if(workspace.windowAdded)workspace.windowAdded.connect('
        '  function(c){_hook(c);_dump();});'
        'if(workspace.windowRemoved)workspace.windowRemoved.connect(_dump);'
        # re-dump on RAISE (click a window behind ours). windowActivated hands
        # us the raised window; _dump forces it to the top of the reported
        # order, because workspace.stackingOrder hasn't settled yet when this
        # fires (relying on it lagged occlusion by one click).
        'if(workspace.windowActivated)workspace.windowActivated.connect(_dump);'
        '_dump();'
    )
    # stable plugin name so a re-launched pet for the SAME session replaces
    # its old script instead of stacking a new one (orphans otherwise pile up
    # and each keeps re-dumping on every geometry change).
    plugin = "claudlet_geom_" + safe
    script_id = None
    qdbus = qdbus_bin()
    path = None
    try:
        subprocess.run([qdbus, "org.kde.KWin", "/Scripting",
                        "org.kde.kwin.Scripting.unloadScript", plugin],
                       timeout=3, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(js)
            path = f.name
        sid = subprocess.check_output(
            [qdbus, "org.kde.KWin", "/Scripting",
             "org.kde.kwin.Scripting.loadScript", path, plugin],
            text=True, timeout=3).strip()
        subprocess.run([qdbus, "org.kde.KWin", "/Scripting",
                        "org.kde.kwin.Scripting.start"], timeout=3)
        script_id = sid          # persistent — do NOT stop now
    except Exception:
        pass
    finally:
        # KWin has read the script by now (loadScript above); always remove the
        # temp .js so a failed load doesn't orphan it (no cleanup glob exists
        # for these, unlike the .port files).
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
    return plugin, script_id


def stop(handle):
    """Unload the geometry KWin script. Best-effort; any failure is swallowed."""
    if handle is None:
        return
    plugin = getattr(handle, "plugin", None)
    if plugin:
        try:
            subprocess.run([qdbus_bin(), "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.unloadScript", plugin],
                           timeout=3, stderr=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL)
        except Exception:
            pass
