"""
app_agent/tools.py — Hybrid Windows GUI automation: pywinauto + Puter AI vision.

Strategy (per action):
  1. Try pywinauto accessibility tree first (fast, exact, no API cost).
  2. If the tree is empty / element not found → fall back to Puter AI vision
     (takes a real screenshot, sends to Claude Sonnet for pixel coordinates).
  3. Use pyautogui to act on those coordinates.

This gives you the best of both worlds:
  - pywinauto: instant, no cost, works perfectly for native Win32/WPF apps.
  - Puter vision: handles Chrome, Electron, web content, dynamic UIs.

New actions exposed to the agent:
  SCREENSHOT        — Real screenshot → Puter vision analysis (replaces accessibility-only SCREENSHOT)
  VISION_CLICK      — Click pixel coordinates from vision (x, y)
  VISION_TYPE       — Type text at current cursor (after a VISION_CLICK)
  VISION_HOTKEY     — Send hotkey via pyautogui (bypasses UIA focus issues)
  VISION_SCROLL     — Scroll at pixel coordinates
  WAIT              — Sleep N seconds

All original pywinauto actions remain unchanged.
"""
from __future__ import annotations

import subprocess
import time
from typing import Optional

try:
    import pywinauto
    from pywinauto import Desktop, Application
    from pywinauto.keyboard import send_keys
    PYWINAUTO_AVAILABLE = True
except ImportError:
    PYWINAUTO_AVAILABLE = False

from app_agent.vision_puter import (
    capture_and_analyse,
    puter_click,
    puter_type,
    puter_hotkey,
    puter_scroll,
    PUTER_AVAILABLE,
)

# Terminal kill-key safety (unchanged from original)
_TERMINAL_KILL_HOTKEYS = {"ctrl+c", "ctrl+z", "ctrl+d", "ctrl+break"}
_BLOCKED_WINDOW_TITLES = {
    "windows terminal", "powershell", "command prompt", "cmd.exe",
    "python", "terminal", "bash", "wsl",
}


def _is_terminal_window(title: str) -> bool:
    t = title.lower()
    return any(blocked in t for blocked in _BLOCKED_WINDOW_TITLES)


def _to_pywinauto_keys(keys: str) -> str:
    key_map = {
        "ctrl": "^", "alt": "%", "shift": "+", "win": "{VK_LWIN}",
        "enter": "{ENTER}", "return": "{ENTER}", "escape": "{ESC}", "esc": "{ESC}",
        "tab": "{TAB}", "space": " ", "delete": "{DELETE}", "del": "{DELETE}",
        "backspace": "{BACKSPACE}", "bs": "{BACKSPACE}", "home": "{HOME}",
        "end": "{END}", "pageup": "{PGUP}", "pgup": "{PGUP}",
        "pagedown": "{PGDN}", "pgdn": "{PGDN}", "up": "{UP}", "down": "{DOWN}",
        "left": "{LEFT}", "right": "{RIGHT}", "insert": "{INSERT}", "ins": "{INSERT}",
        "printscreen": "{PRTSC}",
        "f1": "{F1}", "f2": "{F2}", "f3": "{F3}", "f4": "{F4}",
        "f5": "{F5}", "f6": "{F6}", "f7": "{F7}", "f8": "{F8}",
        "f9": "{F9}", "f10": "{F10}", "f11": "{F11}", "f12": "{F12}",
    }
    normalized = keys.lower().strip().replace(" ", "")
    parts = normalized.split("+")
    combo = ""
    for part in parts:
        combo += key_map.get(part, part)
    return combo


def _tree_is_useful(tree_text: str) -> bool:
    """Return False if the accessibility tree is essentially empty/useless."""
    if not tree_text or "[READ_TREE]" not in tree_text and len(tree_text.strip().splitlines()) <= 2:
        return False
    lines = [l for l in tree_text.splitlines() if l.strip() and "Window:" not in l]
    return len(lines) >= 3


class GUIToolKit:
    def __init__(self):
        self.available = PYWINAUTO_AVAILABLE
        self.vision_available = PUTER_AVAILABLE
        # Last vision result cache — avoids double-screenshotting in one step
        self._last_vision: dict | None = None

    def execute(self, action: dict) -> str:
        if not self.available and action.get("type", "").upper() not in (
            "SCREENSHOT", "VISION_CLICK", "VISION_TYPE", "VISION_HOTKEY", "VISION_SCROLL", "WAIT", "LAUNCH_APP"
        ):
            return (
                "[APP AGENT] pywinauto not installed — accessibility actions unavailable.\n"
                "Vision actions (SCREENSHOT, VISION_CLICK, etc.) still work if PUTER_AUTH_TOKEN is set."
            )

        atype = action.get("type", "").upper()
        try:
            # ── Vision / coordinate actions ─────────────────────────
            if atype == "SCREENSHOT":       return self.screenshot(action.get("hint", ""))
            if atype == "VISION_CLICK":     return self.vision_click(action)
            if atype == "VISION_TYPE":      return puter_type(action.get("text", ""))
            if atype == "VISION_HOTKEY":    return puter_hotkey(*action.get("keys", []))
            if atype == "VISION_SCROLL":    return puter_scroll(
                                                action.get("x", 0), action.get("y", 0),
                                                action.get("amount", 3))
            if atype == "WAIT":             return self.wait(action.get("seconds", 2))

            # ── Accessibility tree actions (pywinauto) ─────────────
            if atype == "READ_TREE":        return self.read_tree(action.get("window", "foreground"))
            if atype == "GET_TEXT":         return self.get_text(action.get("element", ""), action.get("window", "foreground"))
            if atype == "CLICK":            return self.click_smart(action)
            if atype == "DOUBLE_CLICK":     return self.double_click_smart(action)
            if atype == "TYPE_TEXT":        return self.type_text(action.get("text", ""), action.get("element"))
            if atype == "HOTKEY":           return self.hotkey(action.get("keys", ""))
            if atype == "LAUNCH_APP":       return self.launch_app(action.get("app", ""))
            if atype == "FOCUS_WINDOW":     return self.focus_window(action.get("title", ""))
            if atype == "LIST_WINDOWS":     return self.list_windows()
            if atype == "FINISH":           return f"[DONE] {action.get('summary', '')}"

            return f"[ERROR] Unknown action: {atype}"
        except Exception as e:
            return f"[ERROR] {atype} failed: {e}"

    # ── Screenshot + Vision ───────────────────────────────────────────

    def screenshot(self, hint: str = "") -> str:
        """
        Take a real screenshot and analyse it with Puter AI vision.
        Returns a structured description of visible elements with coordinates.
        Falls back to accessibility tree if Puter is unavailable.
        """
        if not self.vision_available:
            # Graceful degradation: return accessibility tree
            if self.available:
                tree = self.read_tree("foreground")
                return (
                    "[SCREENSHOT → ACCESSIBILITY FALLBACK]\n"
                    "Puter vision not available (PUTER_AUTH_TOKEN missing or pyautogui not installed).\n"
                    "Returning accessibility tree instead:\n\n" + tree
                )
            return "[SCREENSHOT] Neither vision nor accessibility tree available."

        result = capture_and_analyse(hint)
        self._last_vision = result

        if "error" in result:
            # Vision failed — fall back to accessibility tree
            fallback = self.read_tree("foreground") if self.available else "(accessibility unavailable)"
            return (
                f"[SCREENSHOT] Vision error: {result['error']}\n"
                f"Accessibility tree fallback:\n{fallback}"
            )

        # Format vision result for the agent
        elements = result.get("visible_elements", [])
        lines = [
            f"[SCREENSHOT] {result.get('screen_state', 'Unknown')}",
            f"Active window: {result.get('active_window', '?')}",
            "",
            "Visible elements (use VISION_CLICK with x,y to interact):",
        ]
        for el in elements:
            lines.append(
                f"  [{el.get('type','?')}] \"{el.get('label','')}\" "
                f"@ ({el.get('x',0)}, {el.get('y',0)}) "
                f"size={el.get('width',0)}×{el.get('height',0)} "
                f"[{el.get('state','?')}]"
            )
        if result.get("text_content"):
            lines.append(f"\nText on screen: {result['text_content'][:300]}")
        if result.get("recommended_next"):
            lines.append(f"\nSuggested next: {result['recommended_next']}")
        if result.get("alerts_or_dialogs"):
            lines.append(f"\n⚠ Dialog/Alert: {result['alerts_or_dialogs']}")

        return "\n".join(lines)

    def vision_click(self, action: dict) -> str:
        """Click at pixel coordinates. Accepts x/y directly from vision output."""
        x = action.get("x")
        y = action.get("y")
        if x is None or y is None:
            return "[VISION_CLICK] Error: x and y coordinates required."
        button = action.get("button", "left")
        clicks = action.get("clicks", 1)
        return puter_click(int(x), int(y), button=button, clicks=clicks)

    def wait(self, seconds) -> str:
        try:
            s = float(seconds)
            time.sleep(s)
            return f"[WAIT] Waited {s}s"
        except Exception as exc:
            return f"[WAIT] Failed: {exc}"

    # ── Smart CLICK: try accessibility tree, fall back to vision ─────

    def click_smart(self, action: dict) -> str:
        """
        Click a UI element by name (accessibility) OR by coordinates (vision).
        If element name is provided, try pywinauto first.
        If that fails AND coordinates are provided, use vision click.
        If that fails AND vision is available, auto-screenshot and try to find it.
        """
        element = action.get("element", "")
        x = action.get("x")
        y = action.get("y")
        control_type = action.get("control_type")

        # Path 1: We have coordinates — use them directly (vision workflow)
        if x is not None and y is not None:
            return puter_click(int(x), int(y))

        # Path 2: Try accessibility tree
        if element and self.available:
            result = self._accessibility_click(element, control_type)
            if "[ERROR]" not in result and "Failed" not in result:
                return result
            # Accessibility failed — try vision
            if self.vision_available:
                return self._vision_find_and_click(element, original_error=result)
            return result

        return "[CLICK] No element name or coordinates provided."

    def _accessibility_click(self, element: str, control_type: Optional[str] = None) -> str:
        try:
            win_obj, title = self._get_foreground()
            if not win_obj:
                return "[CLICK] No foreground window."
            if _is_terminal_window(title):
                return "[CLICK] Refused — target is a terminal window."
            kwargs = {"title_re": f".*{element}.*"}
            if control_type:
                kwargs["control_type"] = control_type
            el = win_obj.child_window(**kwargs)
            el.click_input()
            return f"[CLICK] Clicked '{element}' via accessibility"
        except Exception as e:
            return f"[CLICK] Accessibility failed for '{element}': {e}"

    def _vision_find_and_click(self, label_hint: str, original_error: str = "") -> str:
        """Screenshot, find element by label hint, click its coordinates."""
        vision = capture_and_analyse(f"Find and identify the element labelled '{label_hint}'")
        self._last_vision = vision
        if "error" in vision:
            return f"[CLICK] Accessibility failed AND vision error: {vision['error']}\nOriginal: {original_error}"
        elements = vision.get("visible_elements", [])
        hint_lower = label_hint.lower()
        match = None
        for el in elements:
            if hint_lower in el.get("label", "").lower() or hint_lower in el.get("type", "").lower():
                match = el
                break
        if not match and elements:
            match = elements[0]  # best guess
        if match:
            x, y = match["x"], match["y"]
            result = puter_click(x, y)
            return f"[CLICK] Accessibility failed → vision found '{match.get('label','')}' at ({x},{y}): {result}"
        return f"[CLICK] Element '{label_hint}' not found in accessibility tree OR vision.\nOriginal: {original_error}"

    def double_click_smart(self, action: dict) -> str:
        element = action.get("element", "")
        x = action.get("x")
        y = action.get("y")
        if x is not None and y is not None:
            return puter_click(int(x), int(y), clicks=2)
        if element and self.available:
            try:
                win_obj, title = self._get_foreground()
                if not win_obj:
                    return "[DOUBLE_CLICK] No foreground window."
                if _is_terminal_window(title):
                    return "[DOUBLE_CLICK] Refused — terminal window."
                el = win_obj.child_window(title_re=f".*{element}.*")
                el.double_click_input()
                return f"[DOUBLE_CLICK] Double-clicked '{element}'"
            except Exception as e:
                if self.vision_available:
                    return self._vision_find_and_click(element)
                return f"[DOUBLE_CLICK] Failed: {e}"
        return "[DOUBLE_CLICK] No element name or coordinates provided."

    # ── pywinauto core methods (unchanged from original) ─────────────

    def _get_desktop(self):
        return Desktop(backend="uia")

    def _get_foreground(self):
        try:
            import ctypes
            desktop = self._get_desktop()
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            for w in desktop.windows():
                try:
                    if w.handle == hwnd:
                        return w, w.window_text()
                except Exception:
                    pass
        except Exception:
            pass
        return None, ""

    def _collect_tree(self, element, lines: list, depth: int = 0, max_depth: int = 5) -> None:
        if depth > max_depth:
            return
        try:
            name = element.window_text()
            ctrl_type = element.element_info.control_type or ""
            indent = "  " * depth
            if name.strip():
                lines.append(f"{indent}[{ctrl_type}] {name.strip()}")
        except Exception:
            pass
        try:
            for child in element.children():
                self._collect_tree(child, lines, depth + 1, max_depth)
        except Exception:
            pass

    def read_tree(self, window: str = "foreground") -> str:
        if not self.available:
            return "[READ_TREE] pywinauto not available. Use SCREENSHOT for vision-based analysis."
        desktop = self._get_desktop()
        if window.lower() == "foreground":
            target, title = self._get_foreground()
            if not target:
                return "[READ_TREE] No foreground window found."
        else:
            try:
                target = desktop.window(title_re=f".*{window}.*")
                title = target.window_text()
            except Exception:
                return f"[READ_TREE] No window matching '{window}' found."
        try:
            if _is_terminal_window(title):
                return f"[READ_TREE] '{title}' is a terminal — read-only, will not interact."
            lines = [f"Window: {title}"]
            try:
                root = target.wrapper_object()
            except Exception:
                root = target
            self._collect_tree(root, lines, depth=0)
            if len(lines) <= 1:
                try:
                    for child in target.children():
                        self._collect_tree(child, lines, depth=1)
                except Exception:
                    pass

            tree_text = "\n".join(lines[:150])

            # ── AUTO-FALLBACK: if tree is nearly empty, add vision hint ──
            if not _tree_is_useful(tree_text) and self.vision_available:
                tree_text += (
                    "\n\n[AUTO-HINT] Accessibility tree returned few/no elements "
                    "(common with Chrome, Electron, web apps). "
                    "Use SCREENSHOT to get real visual analysis with pixel coordinates, "
                    "then use VISION_CLICK to interact."
                )
            return tree_text
        except Exception as e:
            return f"[READ_TREE] Failed: {e}"

    def get_text(self, element: str, window: str = "foreground") -> str:
        if not self.available:
            return "[GET_TEXT] pywinauto not available."
        try:
            desktop = self._get_desktop()
            if window.lower() == "foreground":
                win_obj, _ = self._get_foreground()
            else:
                win_obj = desktop.window(title_re=f".*{window}.*")
            if not win_obj:
                return "[GET_TEXT] Window not found."
            if _is_terminal_window(win_obj.window_text()):
                return "[GET_TEXT] Terminal window — read only."
            el = win_obj.child_window(title_re=f".*{element}.*")
            return f"[GET_TEXT] '{element}': {el.window_text()}"
        except Exception as e:
            return f"[GET_TEXT] Failed: {e}"

    def type_text(self, text: str, element: Optional[str] = None) -> str:
        if not self.available:
            # Fall through to vision-based typing
            if element:
                vision_result = self._vision_find_and_click(element)
                if "[ERROR]" in vision_result or "not found" in vision_result:
                    return vision_result
                time.sleep(0.2)
            return puter_type(text)
        try:
            if element:
                self.click_smart({"type": "CLICK", "element": element})
                time.sleep(0.2)
            send_keys(text, with_spaces=True, pause=0.03)
            preview = text[:60] + ("..." if len(text) > 60 else "")
            return f"[TYPE_TEXT] Typed: {preview!r}"
        except Exception as e:
            # Fallback to pyautogui typing
            return puter_type(text)

    def hotkey(self, keys: str) -> str:
        normalized = keys.lower().strip().replace(" ", "")
        _, foreground_title = self._get_foreground() if self.available else (None, "")
        if _is_terminal_window(foreground_title) and normalized in _TERMINAL_KILL_HOTKEYS:
            return (
                f"[HOTKEY] BLOCKED: '{keys}' would kill a process in terminal "
                f"'{foreground_title}'. Focus a different window first."
            )
        # Try pywinauto send_keys first
        if self.available:
            try:
                combo = _to_pywinauto_keys(keys)
                send_keys(combo)
                return f"[HOTKEY] Sent: {keys}"
            except Exception:
                pass
        # Fallback to pyautogui
        parts = normalized.split("+")
        return puter_hotkey(*parts)

    def launch_app(self, app: str) -> str:
        app_map = {
            "notepad": "notepad.exe", "calc": "calc.exe", "calculator": "calc.exe",
            "paint": "mspaint.exe",
            "chrome": (
                r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --force-renderer-accessibility'
                if __import__('os').path.exists(r'C:\Program Files\Google\Chrome\Application\chrome.exe')
                else r'"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --force-renderer-accessibility'
                if __import__('os').path.exists(r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe')
                else "start chrome"
            ),
            "firefox": "firefox.exe", "edge": "msedge.exe",
            "code": "code", "vscode": "code",
            "word": "winword.exe", "excel": "excel.exe", "powerpoint": "powerpnt.exe",
            "explorer": "explorer.exe", "spotify": "spotify.exe",
            "discord": "discord.exe", "vlc": "vlc.exe", "zoom": "zoom.exe",
            "teams": "teams.exe", "slack": "slack.exe", "obs": "obs64.exe",
        }
        exe = app_map.get(app.lower().strip(), app)
        try:
            subprocess.Popen(exe, shell=True)
            time.sleep(1.5)
            return f"[LAUNCH_APP] Launched: {app}"
        except Exception as e:
            return f"[LAUNCH_APP] Failed to launch '{app}': {e}"

    def focus_window(self, title: str) -> str:
        if not self.available:
            return "[FOCUS_WINDOW] pywinauto not available."
        try:
            desktop = self._get_desktop()
            # Collect ALL matching windows — avoid crash when multiple match
            pattern = title.lower()
            candidates = []
            for w in desktop.windows():
                try:
                    t = w.window_text()
                    if t.strip() and pattern in t.lower():
                        candidates.append((w, t))
                except Exception:
                    pass

            if not candidates:
                return f"[FOCUS_WINDOW] No window matching '{title}' found."

            # Pick first non-terminal candidate
            chosen_win, chosen_title = None, ""
            for w, t in candidates:
                if not _is_terminal_window(t):
                    chosen_win, chosen_title = w, t
                    break

            if chosen_win is None:
                return f"[FOCUS_WINDOW] All matching windows are terminals — refused."

            chosen_win.set_focus()
            time.sleep(0.5)
            return f"[FOCUS_WINDOW] Focused: {chosen_title} ({len(candidates)} match(es) found, picked first non-terminal)"
        except Exception as e:
            return f"[FOCUS_WINDOW] Failed: {e}"

    def list_windows(self) -> str:
        if not self.available:
            return "[LIST_WINDOWS] pywinauto not available."
        try:
            desktop = self._get_desktop()
            wins = desktop.windows()
            lines = []
            idx = 0
            for w in wins:
                try:
                    title = w.window_text()
                    if title.strip():
                        flag = " [TERMINAL — DO NOT TOUCH]" if _is_terminal_window(title) else ""
                        lines.append(f"  [{idx}] {title}{flag}")
                        idx += 1
                except Exception:
                    pass
            if not lines:
                return "[LIST_WINDOWS] No visible windows found."
            note = (
                "\nNOTE: If multiple Chrome windows appear, use FOCUS_WINDOW with a "
                "distinctive part of the title (e.g. 'Gmail' if one already shows Gmail). "
                "If none show Gmail yet, use VISION_HOTKEY [ctrl, l] on the current "
                "foreground window to navigate directly — no need to launch a new Chrome."
            )
            return "[LIST_WINDOWS] Open windows:\n" + "\n".join(lines[:30]) + note
        except Exception as e:
            return f"[LIST_WINDOWS] Failed: {e}"


def _tree_is_useful(tree_text: str) -> bool:
    """Return False if the tree has essentially no child elements."""
    if not tree_text:
        return False
    lines = [l for l in tree_text.splitlines() if l.strip() and not l.startswith("Window:")]
    return len(lines) >= 3