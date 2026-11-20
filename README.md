# 3dconnexion-simple-joystick

Use a 3Dconnexion SpaceMouse as a game controller on Windows.

The program reads the SpaceMouse directly and turns it into a **virtual Xbox 360 controller**, **keyboard keys** and **mouse movement**. Almost every PC game supports an Xbox controller, so no game-specific setup is needed. vJoy is not used.

- 6 axes (push/pull/lift and tilt/twist), each with its own deadzone, response curve, sensitivity and invert
- Remap any SpaceMouse button to a controller button, a keyboard key or key combo, a mouse button, or a bridge action
- Hold or toggle buttons
- Change sensitivity live with buttons
- Several profiles, with inheritance, switchable by button or automatically when a game is in front
- Smoothing, dominant-axis mode, and switching translation or rotation off
- Settings live in one `config.json` and reload while the program runs

Tested with a SpaceMouse Pro. Other SpaceMouse models use the same data format and should work, but they haven't been tested.

## Install

1. **Install Python 3.9 or newer** from [python.org](https://www.python.org/downloads/). Tick "Add Python to PATH" in the installer.
2. **Download this project.** Click *Code > Download ZIP* on GitHub and unzip it, or clone it:
   ```
   git clone https://github.com/steffenbk/3dconnexion-simple-joystick.git
   ```
3. **Install the Python packages.** Open a command prompt in the project folder and run:
   ```
   python -m pip install -r requirements.txt
   ```
4. **Install the ViGEmBus driver.** This is what creates the virtual controller. It comes with the `vgamepad` package you just installed. Run this to find the installer:
   ```
   python -c "import vgamepad, os; print(os.path.join(os.path.dirname(vgamepad.__file__), 'win', 'vigem', 'install', 'x64'))"
   ```
   Open the printed folder and run `ViGEmBusSetup_x64.msi`. Alternatively, download it from the [ViGEmBus releases page](https://github.com/nefarius/ViGEmBus/releases). Restarting Windows afterwards is a good idea.

You can leave the 3Dconnexion software (3DxWare) installed. The bridge works alongside it.

## Run

- **`run_monitor.bat`** shows what the SpaceMouse sends (axis values and button numbers) without sending anything. Use it first to see which number each button has.
- **`run_bridge.bat`** starts the bridge. Keep the window open while you play. Closing it removes the virtual controller.

To check the controller works, press `Win+R`, type `joy.cpl`, select the Xbox 360 controller and click *Properties*, then move the SpaceMouse.

Command-line options for `python spacemouse_bridge.py`:

| Option | What it does |
|---|---|
| `--monitor` | Show input only, send nothing |
| `--profile NAME` | Start in this profile |
| `--no-pad` | Keyboard and mouse only, no virtual controller |
| `--config FILE` | Use another settings file |
| `--quiet` | No live status line |
| `--list-keys` | Print every key name you can use |

## Settings (`config.json`)

The file holds **profiles**. One profile is active at a time. Save the file while the bridge is running and the changes apply within about half a second. If you make a typo, the bridge says what is wrong and keeps the old settings.

### Profile options

| Option | Default | Meaning |
|---|---|---|
| `inherits` | none | Start from another profile and change only what you list |
| `sensitivity` | 1.0 | Overall sensitivity for this profile |
| `sens_step` | 0.1 | How much `sens_up` / `sens_down` changes it |
| `smoothing` | 0.0 | 0 = none, 0.9 = very smooth but slower to react |
| `dominant_axis` | false | Only the strongest axis counts, so one movement doesn't leak into others |
| `translation_enabled` | true | Push/pull/lift axes on or off |
| `rotation_enabled` | true | Tilt/twist axes on or off |
| `mouse_speed` | 1500 | Mouse pixels per second at full deflection |

### Axes

The six axes are `tx`, `ty`, `tz` (push/pull/lift) and `rx`, `ry`, `rz` (tilt forward, tilt sideways, twist). Run the monitor to see which is which on your device.

```json
"tx": { "target": "lx", "invert": false, "deadzone": 0.05, "curve": 1.5, "sensitivity": 1.0 }
```

| Field | Meaning |
|---|---|
| `target` | Where the axis goes (see below) |
| `invert` | Flip the direction |
| `deadzone` | Ignore small movements, 0 to 0.95 of the range |
| `curve` | 1 = linear. Above 1 = finer control near the centre |
| `sensitivity` | Multiplier for this axis only |

Targets:

| Target | Meaning |
|---|---|
| `lx`, `ly`, `rx`, `ry` | Left / right stick, X / Y |
| `triggers` | One axis split over both triggers: one direction is RT, the other LT |
| `lt`, `rt` | One trigger, positive direction only |
| `mouse_x`, `mouse_y` | Move the mouse |
| `buttons` | Press something past a threshold: `"pos": "key:W", "neg": "key:S", "threshold": 0.5` |
| `none` | Unused |

An Xbox controller has four full stick axes plus two one-way triggers. So at most five SpaceMouse axes can be smooth controller axes. Send the sixth to buttons, the mouse, or `none`.

### Buttons

Each SpaceMouse button number maps to a **binding**:

| Binding | Example |
|---|---|
| Controller button | `"pad:A"` (A, B, X, Y, LB, RB, LS, RS, START, BACK, GUIDE, DPAD_UP/DOWN/LEFT/RIGHT) |
| Keyboard key | `"key:SPACE"` |
| Key combo | `"key:CTRL+C"` |
| Mouse button | `"mouse:LEFT"` (LEFT, RIGHT, MIDDLE) |
| Toggle instead of hold | `"toggle:key:LSHIFT"` (press once to hold, again to release) |
| Several at once | `["pad:A", "key:F1"]` |
| Bridge action | `"action:sens_up"` |

Actions: `sens_up`, `sens_down`, `sens_reset`, `toggle_pause`, `next_profile`, `prev_profile`, `profile:NAME`, `toggle_translation`, `toggle_rotation`, `toggle_dominant`.

SpaceMouse Pro button numbers: 1 Menu, 2 Fit, 3 T, 5 R, 6 F, 9 Roll, 13-16 keys 1-4, 23 Esc, 24 Alt, 25 Shift, 26 Ctrl, 27 Lock. Other models differ, so check with the monitor.

### Automatic profile switching

```json
"auto_profiles": {
  "enabled": true,
  "apps": { "mygame.exe": "flight" },
  "fallback": "gamepad"
}
```

When the game's window comes to the front, its profile is used. `fallback` (optional) is used for any other window. Find a game's `.exe` name in Task Manager > Details.

### Included profiles

- **gamepad**: translation on the left stick, tilt and twist on the right stick, lift on the triggers, side tilt on the D-pad.
- **flight**: like gamepad, but softer and smoothed.
- **keyboard_mouse**: push/pull/lift as WASD, Space and Ctrl, tilt and twist as mouse look.

## Troubleshooting

- **"No virtual controller"**: the ViGEmBus driver isn't installed (install step 4) or `vgamepad` is missing. Keyboard and mouse bindings still work without it.
- **"Waiting for SpaceMouse"**: the device isn't found. Replug it and check it shows in Device Manager.
- **Keys or mouse do nothing in a game**: if the game runs as administrator, run the bridge as administrator too. Windows blocks input from normal programs into admin programs.
- **The game reacts twice** (to the SpaceMouse itself and to the virtual controller): turn off the SpaceMouse in the game's settings, or set 3DxWare to do nothing for that game.
- **Some anti-cheat systems block virtual controllers.** This tool can't work around that.
- **Wrong direction or wrong button**: run the monitor, then fix `invert` or the button number in `config.json`.

## License

MIT, see [LICENSE](LICENSE).
