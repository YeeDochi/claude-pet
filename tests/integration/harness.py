"""Black-box harness for driving an offscreen Pet through its real socket.

The reactive core's true input is a hook line arriving on the pet's loopback
TCP socket, and its true output is what the pet *displays* (``Pet.snapshot()``).
Testing through these two surfaces — rather than calling ``_handle_event`` and
reading a scatter of private attributes — is what makes the suite survive
internal refactors: rename a method or attribute and only this file (plus
``snapshot``) needs to know.

Usage::

    from harness import pet, send_hook          # `pet` is a pytest fixture

    def test_bash_drives_working(pet):
        send_hook(pet, "PreToolUse", session="a", tool_name="Bash")
        pet._tick()
        assert pet.snapshot()["state"] == "work_computer"

Sibling test modules import this directly (``from harness import ...``); with
pytest's default prepend import mode the test file's directory is on sys.path.
"""
import os
import sys
import json
import socket

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from claudlet import pet as P
from claudlet.core import hostinfo

# One QApplication for the whole test process (Qt forbids a second).
_app = QApplication.instance() or QApplication(sys.argv)


def _deliver(pet, payload, want_reply=False):
    """Connect to the pet's real loopback socket, send ``payload`` bytes, pump
    its socket handler once, and optionally return the reply. The single place
    the suite references the notifier callback (``_on_conn``) and the pet's
    listening socket (``srv``), so those names are coupled here and nowhere else.
    """
    c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c.settimeout(1.0)
    try:
        c.connect((hostinfo.LOOPBACK, pet.srv.getsockname()[1]))
        c.sendall(payload)
        c.shutdown(socket.SHUT_WR)
        pet._on_conn()          # simulate the QSocketNotifier firing
        return c.recv(256).decode() if want_reply else None
    finally:
        c.close()


def send_hook(pet, event=None, **payload):
    """Deliver a hook event to ``pet`` over its REAL loopback socket, framed
    exactly as ``bin/claudlet-hook`` frames it (one JSON line), then pump the
    pet's socket handler once.

    ``event`` is the hook event name (PreToolUse/Stop/SessionEnd/...); extra
    keyword args become payload fields (``session``, ``tool_name``, ...). Omit
    ``event`` and pass ``cmd=...`` to send a command line (motion/quit/ping)::

        send_hook(pet, "PreToolUse", session="a", tool_name="Bash")
        send_hook(pet, cmd="motion", motion="jump", dur=2.0)

    This is the single point in the suite that references the notifier callback,
    so its name is coupled here and nowhere else.
    """
    msg = dict(payload)
    if event is not None:
        msg["event"] = event
    _deliver(pet, (json.dumps(msg) + "\n").encode())


def ping(pet):
    """Send a liveness ping and return the pet's reply string (its banner)."""
    return _deliver(pet, hostinfo.PING, want_reply=True)


@pytest.fixture
def pet():
    """An offscreen Pet, torn down after the test (replaces per-test
    try/finally ``_cleanup``)."""
    p = P.Pet()
    try:
        yield p
    finally:
        p._cleanup()
