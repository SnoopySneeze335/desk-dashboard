# Windows idle screen

There are two ways to show the dashboard when a Windows PC sits idle. **Pick one, not both.**

| | Lively screensaver (recommended) | AutoHotkey crossfade (optional) |
| --- | --- | --- |
| Install | Lively Wallpaper app | AutoHotkey v2 + one script |
| Start | Windows screensaver timer | The script's idle timer |
| Transition | Hard cut to black, then the page fades in | Desktop fades to black, then the page fades in |
| Skips full-screen video | Yes, via Windows' own rules (apps that block the screensaver) | Yes, the script checks the foreground window |
| Lock on return | "On resume, display logon screen" | `LockOnExit := true` in the script |

You need the dashboard URL including your token, for example:

```
https://desk-dashboard.example.ts.net/#token=changeme
```

The part after `#` never leaves your PC. The page saves the token in its own storage and then removes it from the address bar. Add `&pct=1` for percent only, `&view=portfolio` to pin a view, or `&rotate=15` to change the rotation interval.

---

## Option A: Lively Wallpaper as the screensaver

[Lively Wallpaper](https://github.com/rocksdanister/lively) is a free, open-source (GPL-3.0) app that can show a web page as a wallpaper and as a screensaver.

### 1. Install Lively and add the dashboard

1. Install Lively from the Microsoft Store or its GitHub releases page.
2. In Lively, click **+ (Add wallpaper)**, paste the dashboard URL including `#token=…` into the URL box, and confirm.
3. Lively adds it to the library as a webpage wallpaper. You don't have to make it your desktop wallpaper.

### 2. Make Lively the Windows screensaver

1. In Lively's **Settings**, turn on its screensaver support and select the dashboard wallpaper as the screensaver content. The exact menu name depends on the Lively version; look under Settings → General/System for "Screensaver".
2. Open Windows **Screen saver settings** (Start → type "screen saver" → *Change screen saver*).
3. Choose **Lively** in the drop-down.
4. Set **Wait** to **5** minutes.
5. Tick **On resume, display logon screen**.
6. Click **OK**.

### 3. Push display-off and sleep further out

The screensaver should get time to run before the display turns off.

1. Open **Settings → System → Power & battery → Screen, sleep & hibernate timeouts** (on Windows 10: *Power & sleep*).
2. Set **Turn my screen off after** to **1 hour** or more.
3. Set **Make my device sleep after** to something longer than that, or **Never** for a desktop that should keep showing the dashboard.

### Why the start looks like a cut

Windows starts screensavers with a hard cut, with no fade. The dashboard page always starts fully black and fades in over 1.5 seconds once data arrives, which softens the switch. If you want a true crossfade from the desktop, use Option B instead.

---

## Option B: AutoHotkey crossfade (`idle-dashboard.ahk`)

The script fades the desktop to black, opens the dashboard in a full-screen Microsoft Edge kiosk window on the primary monitor, and closes it on any physical keyboard or mouse input. By default it then locks the PC.

**Don't combine this with Option A.** Set the Windows screensaver to *(None)*, or at least give it a longer wait than the script, so the two don't fight.

### Setup

1. Install [AutoHotkey v2](https://www.autohotkey.com/) (v2.0 or later; v1 won't run the script).
2. Copy `idle-dashboard.ahk` to a folder of your own, for example `%USERPROFILE%\DeskDashboard\`. The script creates an `edge-kiosk-profile` folder next to itself, so Edge kiosk mode never touches your normal browser profile.
3. Open the script in a text editor and edit the **Settings** block at the top:

   | Setting | Default | Meaning |
   | --- | --- | --- |
   | `IdleMinutes` | `5` | Minutes without physical input before it starts |
   | `DashboardUrl` | placeholder | Your URL, including `#token=…` |
   | `FadeMs` | `1500` | Fade-to-black duration |
   | `LockOnExit` | `true` | Lock Windows when you come back |
   | `ExcludedProcesses` | a few players and meeting apps | Never start while one of these is in front |
   | `ShowNowHotkey` | `Ctrl+Alt+Win+D` | Test trigger |

4. Double-click the script to run it. A green **H** icon appears in the tray.

### Start it at login

1. Press **Win+R**, type `shell:startup` and press Enter.
2. Right-click in the folder → **New → Shortcut**, and point it at your copy of `idle-dashboard.ahk`.

### Tray menu

- **Enabled**: tick or untick to pause it, for example during a long download you're watching.
- **Show now**: run the full sequence immediately, for testing.
- **Exit**: quit the script.

The **Ctrl+Alt+Win+D** hotkey does the same as **Show now**.

### When it won't start

- The foreground window covers its whole monitor, taskbar included (full-screen video, games, presentations). Maximized windows don't count.
- The foreground app is in `ExcludedProcesses`.
- Windows is already locked.

### Edge flags

The script runs:

```
msedge.exe --kiosk "<URL>" --edge-kiosk-type=fullscreen --no-first-run --user-data-dir="<script folder>\edge-kiosk-profile" --window-position=<primary monitor x>,<y>
```

These are the flags documented in Microsoft's "Configure Microsoft Edge kiosk mode" article. If a future Edge release changes them, update the `cmd` line in `Activate()`.
