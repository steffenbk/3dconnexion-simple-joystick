"""SpaceMouse -> virtual Xbox 360 controller / keyboard / mouse bridge.

Reads a 3Dconnexion SpaceMouse directly over HID (no 3Dconnexion SDK needed)
and turns it into a virtual Xbox 360 controller (through the ViGEmBus driver),
keyboard keys and mouse movement.

    python spacemouse_bridge.py                 run the bridge
    python spacemouse_bridge.py --monitor       only show input, send nothing
    python spacemouse_bridge.py --profile NAME  start in a given profile
    python spacemouse_bridge.py --list-keys     print every usable key name

Edit config.json while it runs; changes are picked up automatically.
"""
import argparse
import ctypes
import json
import os
import struct
import sys
import time

import hid

__version__ = "1.0.0"

VENDOR_IDS = (0x046D, 0x256F)          # old Logitech-era and current 3Dconnexion IDs
AXES = ("tx", "ty", "tz", "rx", "ry", "rz")
TRANSLATION = AXES[:3]
ROTATION = AXES[3:]
FULL_SCALE = 350.0                      # from the device's report descriptor (-350..350)
TICK = 0.01                             # output update interval (100 Hz)
HERE = os.path.dirname(os.path.abspath(__file__))
IS_WINDOWS = sys.platform == "win32"

PAD_BUTTONS = ("A", "B", "X", "Y", "LB", "RB", "LS", "RS", "START", "BACK", "GUIDE",
               "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT")
MOUSE_BUTTONS = ("LEFT", "RIGHT", "MIDDLE")
ACTIONS = ("sens_up", "sens_down", "sens_reset", "toggle_pause", "next_profile",
           "prev_profile", "toggle_translation", "toggle_rotation", "toggle_dominant")
STICK_TARGETS = ("lx", "ly", "rx", "ry")
AXIS_TARGETS = STICK_TARGETS + ("triggers", "lt", "rt", "mouse_x", "mouse_y", "buttons", "none")

# Keyboard scan codes (set 1). Values above 0xFF are extended keys (E0 prefix).
SCANCODES = {
    "ESC": 0x01, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07,
    "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B, "MINUS": 0x0C, "EQUALS": 0x0D,
    "BACKSPACE": 0x0E, "TAB": 0x0F, "Q": 0x10, "W": 0x11, "E": 0x12, "R": 0x13,
    "T": 0x14, "Y": 0x15, "U": 0x16, "I": 0x17, "O": 0x18, "P": 0x19,
    "LBRACKET": 0x1A, "RBRACKET": 0x1B, "ENTER": 0x1C, "LCTRL": 0x1D, "A": 0x1E,
    "S": 0x1F, "D": 0x20, "F": 0x21, "G": 0x22, "H": 0x23, "J": 0x24, "K": 0x25,
    "L": 0x26, "SEMICOLON": 0x27, "APOSTROPHE": 0x28, "GRAVE": 0x29, "LSHIFT": 0x2A,
    "BACKSLASH": 0x2B, "Z": 0x2C, "X": 0x2D, "C": 0x2E, "V": 0x2F, "B": 0x30,
    "N": 0x31, "M": 0x32, "COMMA": 0x33, "PERIOD": 0x34, "SLASH": 0x35,
    "RSHIFT": 0x36, "NUMPAD_MULTIPLY": 0x37, "LALT": 0x38, "SPACE": 0x39,
    "CAPSLOCK": 0x3A, "F1": 0x3B, "F2": 0x3C, "F3": 0x3D, "F4": 0x3E, "F5": 0x3F,
    "F6": 0x40, "F7": 0x41, "F8": 0x42, "F9": 0x43, "F10": 0x44, "NUMLOCK": 0x45,
    "SCROLLLOCK": 0x46, "NUMPAD7": 0x47, "NUMPAD8": 0x48, "NUMPAD9": 0x49,
    "NUMPAD_MINUS": 0x4A, "NUMPAD4": 0x4B, "NUMPAD5": 0x4C, "NUMPAD6": 0x4D,
    "NUMPAD_PLUS": 0x4E, "NUMPAD1": 0x4F, "NUMPAD2": 0x50, "NUMPAD3": 0x51,
    "NUMPAD0": 0x52, "NUMPAD_DECIMAL": 0x53, "F11": 0x57, "F12": 0x58,
    "NUMPAD_ENTER": 0xE01C, "RCTRL": 0xE01D, "NUMPAD_DIVIDE": 0xE035, "RALT": 0xE038,
    "HOME": 0xE047, "UP": 0xE048, "PGUP": 0xE049, "LEFT": 0xE04B, "RIGHT": 0xE04D,
    "END": 0xE04F, "DOWN": 0xE050, "PGDN": 0xE051, "INSERT": 0xE052,
    "DELETE": 0xE053, "LWIN": 0xE05B,
}
KEY_ALIASES = {"CTRL": "LCTRL", "SHIFT": "LSHIFT", "ALT": "LALT", "WIN": "LWIN",
               "RETURN": "ENTER", "ESCAPE": "ESC", "DEL": "DELETE",
               "PAGEUP": "PGUP", "PAGEDOWN": "PGDN"}


def clamp(v, lo=-1.0, hi=1.0):
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- input ----

def find_device():
    """First HID interface that is a multi-axis controller (usage page 1, usage 8)."""
    for vid in VENDOR_IDS:
        for d in hid.enumerate(vid, 0):
            if d["usage_page"] == 0x01 and d["usage"] == 0x08:
                return d
    return None


class SpaceMouseState:
    def __init__(self):
        self.axes = dict.fromkeys(AXES, 0)
        self.buttons = set()

    def feed(self, report):
        data = bytes(report)
        rid = data[0]
        if rid == 1:
            # Older models: report 1 = translation only (6 bytes).
            # Newer models: report 1 = all six axes (12 bytes).
            n = 6 if len(data) >= 13 else 3
            for k, v in zip(AXES, struct.unpack_from("<%dh" % n, data, 1)):
                self.axes[k] = v
        elif rid == 2 and len(data) >= 7:
            for k, v in zip(ROTATION, struct.unpack_from("<3h", data, 1)):
                self.axes[k] = v
        elif rid == 3:
            bits = int.from_bytes(data[1:], "little")
            # Bit i = button i+1 (matches the descriptor's usage numbering).
            self.buttons = {i + 1 for i in range((len(data) - 1) * 8) if bits >> i & 1}

    def clear(self):
        self.axes = dict.fromkeys(AXES, 0)
        self.buttons = set()


# ------------------------------------------------------------- bindings ----

class Binding:
    """What one button (or one axis direction) does: held outputs + actions."""

    def __init__(self, atoms=(), actions=(), toggle=False):
        self.atoms = frozenset(atoms)     # ("pad", "A"), ("key", "W"), ("mouse", "LEFT")
        self.actions = tuple(actions)     # "sens_up", "profile:flight", ...
        self.toggle = toggle


def parse_binding(spec):
    """'pad:A' | 'key:CTRL+C' | 'mouse:LEFT' | 'action:sens_up' | 'toggle:<one of those>'
    or a list of them (all fire together)."""
    if isinstance(spec, list):
        parts = [parse_binding(s) for s in spec]
        return Binding(set().union(*(p.atoms for p in parts)),
                       [a for p in parts for a in p.actions],
                       any(p.toggle for p in parts))
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("binding must be a text like 'pad:A', got %r" % (spec,))
    s = spec.strip()
    toggle = False
    if s.lower().startswith("toggle:"):
        toggle, s = True, s[7:]
    kind, sep, value = s.partition(":")
    if not sep:                                   # bare 'A' means a pad button
        kind, value = "pad", s
    kind = kind.lower()
    if kind == "pad":
        v = value.upper()
        if v not in PAD_BUTTONS:
            raise ValueError("unknown pad button '%s' (use one of %s)" % (value, ", ".join(PAD_BUTTONS)))
        return Binding([("pad", v)], toggle=toggle)
    if kind == "key":
        atoms = []
        for k in value.split("+"):
            k = KEY_ALIASES.get(k.strip().upper(), k.strip().upper())
            if k not in SCANCODES:
                raise ValueError("unknown key '%s' (run with --list-keys)" % k)
            atoms.append(("key", k))
        return Binding(atoms, toggle=toggle)
    if kind == "mouse":
        v = value.upper()
        if v not in MOUSE_BUTTONS:
            raise ValueError("unknown mouse button '%s' (use LEFT, RIGHT or MIDDLE)" % value)
        return Binding([("mouse", v)], toggle=toggle)
    if kind == "action":
        v = value.strip()
        if v not in ACTIONS and not v.startswith("profile:"):
            raise ValueError("unknown action '%s' (use one of %s, profile:NAME)" % (v, ", ".join(ACTIONS)))
        return Binding(actions=[v])
    raise ValueError("unknown binding type '%s' in '%s' (use pad:, key:, mouse:, action:)" % (kind, spec))


# -------------------------------------------------------------- profiles ----

class Profile:
    def __init__(self, name, d):
        self.name = name
        self.sensitivity = float(d.get("sensitivity", 1.0))
        self.sens_step = float(d.get("sens_step", 0.1))
        self.smoothing = clamp(float(d.get("smoothing", 0.0)), 0.0, 0.95)
        self.dominant_axis = bool(d.get("dominant_axis", False))
        self.translation = bool(d.get("translation_enabled", True))
        self.rotation = bool(d.get("rotation_enabled", True))
        self.mouse_speed = float(d.get("mouse_speed", 1500.0))   # pixels/second at full push
        axes = {k: v for k, v in d.get("axes", {}).items() if not k.startswith("_")}
        for k in axes:
            if k not in AXES:
                raise ValueError("unknown axis '%s' (use %s)" % (k, ", ".join(AXES)))
        self.axes = {}
        for ax in AXES:
            ac = dict(axes.get(ax, {}))
            tgt = ac.get("target", "none")
            if tgt not in AXIS_TARGETS:
                raise ValueError("axis %s: unknown target '%s' (use %s)" % (ax, tgt, ", ".join(AXIS_TARGETS)))
            ac["_pos"] = parse_binding(ac["pos"]) if tgt == "buttons" and ac.get("pos") else None
            ac["_neg"] = parse_binding(ac["neg"]) if tgt == "buttons" and ac.get("neg") else None
            self.axes[ax] = ac
        self.buttons = {}
        for k, v in d.get("buttons", {}).items():
            if str(k).startswith("_"):
                continue
            try:
                num = int(k)
            except ValueError:
                raise ValueError("button '%s' must be a number (run --monitor to see them)" % k)
            try:
                self.buttons[num] = parse_binding(v)
            except ValueError as e:
                raise ValueError("button %s: %s" % (k, e))


def resolve_profiles(raw):
    """Apply 'inherits' and build Profile objects, in config order."""
    profs = {k: v for k, v in (raw.get("profiles") or {}).items() if not k.startswith("_")}
    if not profs:
        raise ValueError("config has no profiles")
    merged = {}

    def get(name, chain=()):
        if name in merged:
            return merged[name]
        if name not in profs:
            raise ValueError("unknown profile '%s'" % name)
        if name in chain:
            raise ValueError("profile inherit loop: %s" % " -> ".join(chain + (name,)))
        p = profs[name]
        base = p.get("inherits")
        if base:
            b = get(base, chain + (name,))
            m = {k: v for k, v in b.items() if k not in ("axes", "buttons")}
            m["axes"] = {a: dict(c) for a, c in b["axes"].items()}
            m["buttons"] = dict(b["buttons"])
        else:
            m = {"axes": {}, "buttons": {}}
        for k, v in p.items():
            if k == "axes":
                for a, c in v.items():
                    m["axes"].setdefault(a, {}).update(c)
            elif k == "buttons":
                m["buttons"].update(v)
            elif k != "inherits":
                m[k] = v
        merged[name] = m
        return m

    out = {}
    for name in profs:
        try:
            out[name] = Profile(name, get(name))
        except ValueError as e:
            raise ValueError("profile '%s': %s" % (name, e))
    for a in ((raw.get("auto_profiles") or {}).get("apps") or {}).values():
        if a not in out:
            raise ValueError("auto_profiles points to unknown profile '%s'" % a)
    return out


class Config:
    def __init__(self, path):
        self.path, self.mtime = path, None
        self.raw, self.profiles = {}, {}
        self.reload()

    def reload(self):
        try:
            m = os.path.getmtime(self.path)
        except OSError as e:
            if self.mtime is None:
                sys.exit("Cannot read config %s: %s" % (self.path, e))
            return False
        if m == self.mtime:
            return False
        self.mtime = m
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            profiles = resolve_profiles(raw)
        except (OSError, ValueError) as e:
            if not self.profiles:
                sys.exit("Config error in %s:\n  %s" % (self.path, e))
            print("\nConfig error, keeping previous settings:\n  %s" % e)
            return False
        self.raw, self.profiles = raw, profiles
        return True


# ---------------------------------------------------------------- output ----

if IS_WINDOWS:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    _user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
    _user32.SendInput.restype = wintypes.UINT
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                                     wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    _MOUSE_FLAGS = {"LEFT": (0x0002, 0x0004), "RIGHT": (0x0008, 0x0010), "MIDDLE": (0x0020, 0x0040)}

    def _send(inp):
        return _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    def send_key(name, down):
        code = SCANCODES[name]
        flags = 0x0008                                  # KEYEVENTF_SCANCODE (games want scan codes)
        if code > 0xFF:
            flags |= 0x0001                             # KEYEVENTF_EXTENDEDKEY
        if not down:
            flags |= 0x0002                             # KEYEVENTF_KEYUP
        inp = _INPUT(type=1)
        inp.u.ki = _KEYBDINPUT(0, code & 0xFF, flags, 0, 0)
        _send(inp)

    def send_mouse_button(name, down):
        inp = _INPUT(type=0)
        inp.u.mi = _MOUSEINPUT(0, 0, 0, _MOUSE_FLAGS[name][0 if down else 1], 0, 0)
        _send(inp)

    def send_mouse_move(dx, dy):
        inp = _INPUT(type=0)
        inp.u.mi = _MOUSEINPUT(dx, dy, 0, 0x0001, 0, 0)  # MOUSEEVENTF_MOVE (relative)
        return _send(inp)

    def foreground_exe():
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = _kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = wintypes.DWORD(len(buf))
            if not _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                return None
            return os.path.basename(buf.value).lower()
        finally:
            _kernel32.CloseHandle(h)
else:
    def send_key(name, down): pass
    def send_mouse_button(name, down): pass
    def send_mouse_move(dx, dy): pass
    def foreground_exe(): return None


class VirtualPad:
    NAMES = {"A": "A", "B": "B", "X": "X", "Y": "Y", "LB": "LEFT_SHOULDER",
             "RB": "RIGHT_SHOULDER", "LS": "LEFT_THUMB", "RS": "RIGHT_THUMB",
             "START": "START", "BACK": "BACK", "GUIDE": "GUIDE",
             "DPAD_UP": "DPAD_UP", "DPAD_DOWN": "DPAD_DOWN",
             "DPAD_LEFT": "DPAD_LEFT", "DPAD_RIGHT": "DPAD_RIGHT"}

    def __init__(self):
        import vgamepad as vg
        self.pad = vg.VX360Gamepad()
        self.btn = {k: getattr(vg.XUSB_BUTTON, "XUSB_GAMEPAD_" + v) for k, v in self.NAMES.items()}

    def apply(self, sticks, pressed):
        p = self.pad
        p.left_joystick_float(sticks["lx"], sticks["ly"])
        p.right_joystick_float(sticks["rx"], sticks["ry"])
        p.left_trigger_float(sticks["lt"])
        p.right_trigger_float(sticks["rt"])
        for name, code in self.btn.items():
            (p.press_button if name in pressed else p.release_button)(button=code)
        p.update()

    def neutral(self):
        self.pad.reset()
        self.pad.update()


class Outputs:
    def __init__(self, want_pad):
        self.pad = None
        if want_pad:
            try:
                self.pad = VirtualPad()
                print("Virtual Xbox 360 controller created.")
            except Exception as e:  # missing package or missing ViGEmBus driver
                print("No virtual controller (%s).\n"
                      "Keyboard and mouse bindings still work. For the controller, install the\n"
                      "ViGEmBus driver and 'pip install vgamepad' (see README)." % e)
        self.input_held = set()
        self.mouse_frac = [0.0, 0.0]
        self.last_pad = None

    def apply(self, sticks, held, mouse):
        if self.pad:
            pad_names = frozenset(v for k, v in held if k == "pad")
            key = (tuple(round(sticks[k], 4) for k in ("lx", "ly", "rx", "ry", "lt", "rt")), pad_names)
            if key != self.last_pad:
                self.pad.apply(sticks, pad_names)
                self.last_pad = key
        want = {a for a in held if a[0] in ("key", "mouse")}
        for a in sorted(self.input_held - want):
            self._press(a, False)
        for a in sorted(want - self.input_held):
            self._press(a, True)
        self.input_held = want
        dx = mouse[0] + self.mouse_frac[0]
        dy = mouse[1] + self.mouse_frac[1]
        ix, iy = int(dx), int(dy)
        self.mouse_frac = [dx - ix, dy - iy]
        if ix or iy:
            send_mouse_move(ix, iy)

    @staticmethod
    def _press(atom, down):
        kind, name = atom
        (send_key if kind == "key" else send_mouse_button)(name, down)

    def neutral(self):
        for a in sorted(self.input_held):
            self._press(a, False)
        self.input_held = set()
        self.mouse_frac = [0.0, 0.0]
        if self.pad and self.last_pad is not None:
            self.pad.neutral()
        self.last_pad = None


# ---------------------------------------------------------------- engine ----

def shape(raw, ac, sens):
    """Raw axis value -> -1..1 after sensitivity, invert, deadzone and curve."""
    v = raw / FULL_SCALE * ac.get("sensitivity", 1.0) * sens
    if ac.get("invert"):
        v = -v
    dz = clamp(ac.get("deadzone", 0.05), 0.0, 0.95)
    a = abs(v)
    if a <= dz:
        return 0.0
    a = min(1.0, (a - dz) / (1.0 - dz)) ** ac.get("curve", 1.0)
    return a if v > 0 else -a


class Engine:
    def __init__(self, config, outputs, start_profile=None):
        self.config = config
        self.outputs = outputs
        self.sens_mult = 1.0
        self.paused = False
        self.smooth = dict.fromkeys(AXES, 0.0)
        self.prev_active = {}
        self.toggled = {}
        self.last = None
        self.profile = None
        name = start_profile or config.raw.get("active_profile")
        if name not in config.profiles:
            if start_profile:
                sys.exit("No profile named '%s'. Profiles: %s" % (start_profile, ", ".join(config.profiles)))
            name = next(iter(config.profiles))
        self.set_profile(name, announce=False)

    # --- state changes ---
    def set_profile(self, name, announce=True):
        if name not in self.config.profiles:
            print("\nNo profile named '%s'." % name)
            return
        self.profile = self.config.profiles[name]
        self.trans_on = self.profile.translation
        self.rot_on = self.profile.rotation
        self.dominant = self.profile.dominant_axis
        self.toggled = {}
        if announce:
            print("\nProfile: %s" % name)

    def config_reloaded(self):
        name = self.profile.name
        self.profile = None
        self.set_profile(name if name in self.config.profiles else next(iter(self.config.profiles)),
                         announce=False)

    def run_action(self, a):
        p = self.profile
        names = list(self.config.profiles)
        if a == "sens_up":
            self.sens_mult = round(min(5.0, self.sens_mult + p.sens_step), 3)
        elif a == "sens_down":
            self.sens_mult = round(max(0.1, self.sens_mult - p.sens_step), 3)
        elif a == "sens_reset":
            self.sens_mult = 1.0
        elif a == "toggle_pause":
            self.paused = not self.paused
            print("\n" + ("Paused." if self.paused else "Resumed."))
            return
        elif a in ("next_profile", "prev_profile"):
            i = names.index(p.name) + (1 if a == "next_profile" else -1)
            self.set_profile(names[i % len(names)])
            return
        elif a.startswith("profile:"):
            self.set_profile(a[8:])
            return
        elif a == "toggle_translation":
            self.trans_on = not self.trans_on
            print("\nTranslation " + ("on." if self.trans_on else "off."))
            return
        elif a == "toggle_rotation":
            self.rot_on = not self.rot_on
            print("\nRotation " + ("on." if self.rot_on else "off."))
            return
        elif a == "toggle_dominant":
            self.dominant = not self.dominant
            print("\nDominant axis " + ("on." if self.dominant else "off."))
            return
        print("\nSensitivity %.2fx" % self.sens_mult)

    # --- one update ---
    def step(self, state, dt):
        p = self.profile
        sens = p.sensitivity * self.sens_mult
        vals = {}
        for ax in AXES:
            on = not self.paused and (self.trans_on if ax in TRANSLATION else self.rot_on)
            v = shape(state.axes[ax], p.axes[ax], sens) if on else 0.0
            if p.smoothing > 0:
                s = self.smooth[ax] + (v - self.smooth[ax]) * (1.0 - p.smoothing)
                if v == 0.0 and abs(s) < 1e-3:
                    s = 0.0
                self.smooth[ax] = v = s
            vals[ax] = v
        if self.dominant:
            top = max(AXES, key=lambda a: abs(vals[a]))
            vals = {a: (vals[a] if a == top else 0.0) for a in AXES}

        sticks = dict(lx=0.0, ly=0.0, rx=0.0, ry=0.0, lt=0.0, rt=0.0)
        mouse = [0.0, 0.0]
        active = {}
        for ax in AXES:
            ac, v = p.axes[ax], vals[ax]
            tgt = ac.get("target", "none")
            if tgt in STICK_TARGETS:
                sticks[tgt] = clamp(sticks[tgt] + v)
            elif tgt == "triggers":               # one axis split over both triggers
                sticks["rt"] = max(sticks["rt"], v)
                sticks["lt"] = max(sticks["lt"], -v)
            elif tgt in ("lt", "rt"):
                sticks[tgt] = max(sticks[tgt], v)
            elif tgt == "mouse_x":
                mouse[0] += v * p.mouse_speed * dt
            elif tgt == "mouse_y":
                mouse[1] += v * p.mouse_speed * dt
            elif tgt == "buttons":
                thr = ac.get("threshold", 0.5)
                if ac["_pos"]:
                    active[("axis", ax, "+")] = (v > thr, ac["_pos"])
                if ac["_neg"]:
                    active[("axis", ax, "-")] = (v < -thr, ac["_neg"])
        for b, binding in p.buttons.items():
            active[("btn", b)] = (b in state.buttons, binding)

        held = set()
        for src, (on, binding) in active.items():
            if on and not self.prev_active.get(src, False):
                for a in binding.actions:
                    self.run_action(a)
                if binding.toggle:
                    self.toggled[src] = not self.toggled.get(src, False)
            if (self.toggled.get(src, False) if binding.toggle else on):
                held |= binding.atoms
        self.prev_active = {src: on for src, (on, _) in active.items()}
        self.last = (vals, sticks, held)

        if self.outputs:
            if self.paused:
                self.outputs.neutral()
            else:
                self.outputs.apply(sticks, held, mouse)

    def status_line(self, state):
        vals, sticks, held = self.last
        ax = " ".join("%s%+5d" % (k, state.axes[k]) for k in AXES)
        st = "L(%+.2f,%+.2f) R(%+.2f,%+.2f) LT%.2f RT%.2f" % (
            sticks["lx"], sticks["ly"], sticks["rx"], sticks["ry"], sticks["lt"], sticks["rt"])
        btn = ",".join(str(b) for b in sorted(state.buttons)) or "-"
        out = ",".join(sorted("%s:%s" % a for a in held)) or "-"
        flag = " PAUSED" if self.paused else ""
        return "\r[%s %.1fx%s] %s | %s | btn %s -> %s     " % (
            self.profile.name, self.sens_mult, flag, ax, st, btn, out)


# ------------------------------------------------------------------ main ----

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--profile", help="profile to start in")
    ap.add_argument("--monitor", action="store_true", help="show input only, send nothing")
    ap.add_argument("--no-pad", action="store_true", help="don't create the virtual controller")
    ap.add_argument("--quiet", action="store_true", help="no live status line")
    ap.add_argument("--list-keys", action="store_true", help="print usable key names and exit")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()

    if args.list_keys:
        print(" ".join(SCANCODES))
        print("Aliases: " + ", ".join("%s=%s" % kv for kv in KEY_ALIASES.items()))
        return

    cfg = Config(args.config)
    outputs = None if args.monitor else Outputs(want_pad=not args.no_pad)
    engine = Engine(cfg, outputs, args.profile)
    print("SpaceMouse bridge %s - profile '%s' (Ctrl+C to quit)" % (__version__, engine.profile.name))

    auto = lambda: cfg.raw.get("auto_profiles") or {}
    last_exe = None
    state = SpaceMouseState()
    try:
        while True:
            info = find_device()
            if not info:
                print("\rWaiting for SpaceMouse...   ", end="", flush=True)
                time.sleep(1.0)
                continue
            dev = hid.device()
            try:
                dev.open_path(info["path"])
            except OSError as e:
                print("\rCannot open SpaceMouse (%s), retrying...   " % e, end="", flush=True)
                time.sleep(1.0)
                continue
            print("\nConnected: %s" % info["product_string"])
            last_tick = time.perf_counter()
            ticks = 0
            last_line = None
            try:
                while True:
                    report = dev.read(64, 5)
                    if report:
                        state.feed(report)
                    now = time.perf_counter()
                    if now - last_tick < TICK:
                        continue
                    dt, last_tick = min(now - last_tick, 0.1), now
                    ticks += 1
                    if ticks % 50 == 0 and cfg.reload():
                        engine.config_reloaded()
                        print("\nConfig reloaded.")
                    if ticks % 50 == 25 and auto().get("enabled"):
                        exe = foreground_exe()
                        if exe and exe != last_exe:
                            last_exe = exe
                            apps = {k.lower(): v for k, v in (auto().get("apps") or {}).items()}
                            target = apps.get(exe) or auto().get("fallback")
                            if target and target != engine.profile.name:
                                engine.set_profile(target)
                    engine.step(state, dt)
                    if not args.quiet:
                        line = engine.status_line(state)
                        if line != last_line:
                            print(line, end="", flush=True)
                            last_line = line
            except OSError:
                print("\nSpaceMouse disconnected.")
                state.clear()
                if outputs:
                    outputs.neutral()
            finally:
                dev.close()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        if outputs:
            outputs.neutral()


if __name__ == "__main__":
    main()
