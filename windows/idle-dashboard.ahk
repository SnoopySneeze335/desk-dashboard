; SPDX-License-Identifier: GPL-3.0-or-later
;
; Desk Dashboard idle screen for Windows (AutoHotkey v2).
;
; After a few idle minutes, fades the screen to black, opens the dashboard in
; a full-screen Microsoft Edge kiosk window on the primary monitor and lets the
; page fade itself in. Any physical keyboard or mouse input closes it and, by
; default, locks the workstation.
;
; Don't combine this with the Lively screensaver route (see LIVELY.md): pick one.
; Start at login: put a shortcut to this script in shell:startup (see LIVELY.md).

#Requires AutoHotkey v2.0
#SingleInstance Force
Persistent
InstallKeybdHook()
InstallMouseHook()

; ============================== Settings =====================================
IdleMinutes := 5
; Your dashboard address including the token fragment. Placeholder shown:
DashboardUrl := "https://desk-dashboard.example.ts.net/#token=changeme"
FadeMs := 1500
LockOnExit := true
; Never activate while one of these is the foreground process (case-insensitive).
ExcludedProcesses := ["vlc.exe", "mpc-hc64.exe", "obs64.exe", "zoom.exe", "ms-teams.exe", "Teams.exe"]
; Test hotkey: Ctrl+Alt+Win+D shows the dashboard immediately.
ShowNowHotkey := "^!#d"
; Longest wait for the page to load before the black overlay is removed anyway.
PageLoadTimeoutMs := 15000
; The page's <title>; Edge shows it as the window title once the page has loaded.
PageTitle := "Desk Dashboard"
; Separate Edge profile so kiosk mode never touches your normal browser session.
ProfileDir := A_ScriptDir "\edge-kiosk-profile"
; =============================================================================

Enabled := true
Active := false
Overlay := ""
EdgePid := 0
ArmedAt := 0          ; A_TickCount after which physical input ends the idle screen

SetupTray()
Hotkey(ShowNowHotkey, (*) => ShowNow())
SetTimer(CheckIdle, 1000)

; ------------------------------------------------------------------------------

SetupTray() {
    A_IconTip := "Desk Dashboard idle screen"
    tray := A_TrayMenu
    tray.Delete()
    tray.Add("Enabled", ToggleEnabled)
    tray.Check("Enabled")
    tray.Add("Show now", (*) => ShowNow())
    tray.Add()
    tray.Add("Exit", (*) => ExitApp())
    tray.Default := "Show now"
}

ToggleEnabled(itemName, *) {
    global Enabled
    Enabled := !Enabled
    if Enabled
        A_TrayMenu.Check(itemName)
    else
        A_TrayMenu.Uncheck(itemName)
}

ShowNow() {
    ; Let the hotkey's own keys come up first so their release doesn't count as input.
    KeyWait("Ctrl"), KeyWait("Alt"), KeyWait("LWin"), KeyWait("RWin"), KeyWait("d")
    Activate(1500)
}

CheckIdle() {
    if !Enabled || Active
        return
    if A_TimeIdlePhysical < IdleMinutes * 60000
        return
    if ShouldSkip()
        return
    Activate(0)
}

; True when the user is watching something or the session is locked.
ShouldSkip() {
    if ProcessExist("LogonUI.exe")      ; locked or at the sign-in screen
        return true
    try {
        hwnd := WinGetID("A")
    } catch {
        return false
    }
    try {
        exe := WinGetProcessName(hwnd)
        for name in ExcludedProcesses
            if StrLower(exe) = StrLower(name)
                return true
    }
    return CoversWholeMonitor(hwnd)
}

; Full-screen video, games and presentations cover their entire monitor,
; taskbar included. Maximized windows don't. The desktop itself is ignored.
CoversWholeMonitor(hwnd) {
    try {
        cls := WinGetClass(hwnd)
        if (cls = "Progman" || cls = "WorkerW" || cls = "Shell_TrayWnd")
            return false
        WinGetPos(&x, &y, &w, &h, hwnd)
    } catch {
        return false
    }
    hMon := DllCall("MonitorFromWindow", "ptr", hwnd, "uint", 2, "ptr") ; MONITOR_DEFAULTTONEAREST
    info := Buffer(40, 0)
    NumPut("uint", 40, info, 0)
    if !DllCall("GetMonitorInfo", "ptr", hMon, "ptr", info)
        return false
    left := NumGet(info, 4, "int"), top := NumGet(info, 8, "int")
    right := NumGet(info, 12, "int"), bottom := NumGet(info, 16, "int")
    return x <= left && y <= top && x + w >= right && y + h >= bottom
}

InputSinceArmed() {
    elapsed := A_TickCount - ArmedAt
    return elapsed > 0 && A_TimeIdlePhysical < elapsed
}

; ------------------------------------------------------------------------------

Activate(graceMs) {
    global Active, Overlay, EdgePid, ArmedAt
    if Active
        return
    edge := FindEdge()
    if (edge = "") {
        TrayTip("Microsoft Edge not found", "Desk Dashboard", 3)
        return
    }
    Active := true
    ArmedAt := A_TickCount + graceMs

    MonitorGet(MonitorGetPrimary(), &left, &top, &right, &bottom)

    ; 1. Fade a borderless, always-on-top black overlay in.
    Overlay := Gui("+AlwaysOnTop -Caption +ToolWindow +E0x20")  ; E0x20: click-through
    Overlay.BackColor := "000000"
    Overlay.Show(Format("x{} y{} w{} h{} NoActivate", left, top, right - left, bottom - top))
    WinSetTransparent(0, Overlay)
    SetTimer(WatchInput, 50)
    start := A_TickCount
    while (A_TickCount - start < FadeMs) {
        if !Active
            return
        WinSetTransparent(Round(255 * (A_TickCount - start) / FadeMs), Overlay)
        Sleep(15)
    }
    if !Active
        return
    WinSetTransparent(255, Overlay)

    ; 2. Launch Edge full-screen kiosk on the primary monitor with its own profile.
    cmd := Format('"{1}" --kiosk "{2}" --edge-kiosk-type=fullscreen --no-first-run '
        . '--user-data-dir="{3}" --window-position={4},{5}', edge, DashboardUrl, ProfileDir, left, top)
    try {
        Run(cmd, , , &pid)
        EdgePid := pid
    } catch {
        Deactivate(false)
        return
    }

    ; 3. Remove the overlay once the page has loaded; the page fades in from black.
    WinWait(PageTitle " ahk_exe msedge.exe", , PageLoadTimeoutMs / 1000)
    if !Active
        return
    Sleep(300)
    try WinActivate(PageTitle " ahk_exe msedge.exe")
    if IsObject(Overlay) {
        Overlay.Destroy()
        Overlay := ""
    }
}

WatchInput() {
    if Active && InputSinceArmed()
        Deactivate(LockOnExit)
}

Deactivate(lock) {
    global Active, Overlay, EdgePid
    if !Active
        return
    Active := false
    SetTimer(WatchInput, 0)
    CloseKiosk()
    if IsObject(Overlay) {
        Overlay.Destroy()
        Overlay := ""
    }
    if lock
        DllCall("LockWorkStation")
}

; Close every Edge process that uses the kiosk profile, and nothing else.
CloseKiosk() {
    global EdgePid
    try {
        wmi := ComObjGet("winmgmts:")
        for proc in wmi.ExecQuery("SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name = 'msedge.exe'") {
            if InStr(proc.CommandLine, ProfileDir)
                ProcessClose(proc.ProcessId)
        }
    }
    if EdgePid
        try ProcessClose(EdgePid)
    EdgePid := 0
}

FindEdge() {
    candidates := [
        EnvGet("ProgramFiles(x86)") "\Microsoft\Edge\Application\msedge.exe",
        EnvGet("ProgramFiles") "\Microsoft\Edge\Application\msedge.exe"
    ]
    for path in candidates
        if FileExist(path)
            return path
    try return RegRead("HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe")
    return ""
}

OnExit((*) => Deactivate(false))
