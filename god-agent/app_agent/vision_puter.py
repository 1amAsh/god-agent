"""
app_agent/vision_puter.py — Puter AI vision for the App Agent.

Captures a real screenshot and sends it to Claude via Puter's
OpenAI-compatible API for pixel-accurate GUI element analysis.
"""
from __future__ import annotations

import base64
import os
import time
import json
from pathlib import Path
from datetime import datetime

PUTER_BASE_URL   = "https://api.puter.com/puterai/openai/v1/"
# Try in order — first one that works wins
VISION_MODELS    = [
    "google/gemini-2.5-flash",
    "gpt-4o",
]
SCREENSHOT_DIR   = Path("screenshots")

VISION_SYSTEM_PROMPT = """
You are a GUI screen analyser. Given a screenshot, return ONLY a JSON object — no markdown, no prose.

{
  "screen_state": "one line: what app/page is visible",
  "active_window": "window title or 'desktop'",
  "visible_elements": [
    {
      "type": "button|text_field|search_bar|video_thumbnail|link|icon|menu|tab|address_bar|other",
      "label": "exact visible text or best description",
      "x": <integer pixel x of element CENTER>,
      "y": <integer pixel y of element CENTER>,
      "width": <integer>,
      "height": <integer>,
      "state": "enabled|focused|selected|disabled"
    }
  ],
  "text_content": "important readable text on screen",
  "alerts_or_dialogs": null,
  "recommended_next": "specific next action e.g. 'Click Compose button at (93, 320)'"
}

Rules:
- Coordinates must match the actual screenshot pixel dimensions.
- List every interactive element visible. Never omit search bars, compose buttons, or input fields.
- For Gmail: identify Compose button, To/Subject/Body fields, Send button by their exact positions.
- Be precise. Note uncertainty in the label if unsure.
""".strip()


def _ensure_screenshot_dir() -> Path:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SCREENSHOT_DIR


def _puter_client():
    from openai import OpenAI
    token = os.environ.get("PUTER_AUTH_TOKEN", "")
    if not token:
        raise RuntimeError(
            "PUTER_AUTH_TOKEN not set in .env\n"
            "Get one free: https://puter.com → F12 console → type: puter.authToken"
        )
    return OpenAI(api_key=token, base_url=PUTER_BASE_URL)


def _take_screenshot(max_width: int = 1024) -> Path:
    """Capture desktop, downscale to 1024px wide (smaller = less chance of 400), save as JPEG."""
    try:
        import pyautogui
        from PIL import Image
        img = pyautogui.screenshot()
        w, h = img.size
        if w > max_width:
            ratio = max_width / w
            img = img.resize((max_width, int(h * ratio)), Image.LANCZOS)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:20]
        path = _ensure_screenshot_dir() / f"vision_{ts}.jpg"
        # quality=65 keeps file small — reduces 400 errors from payload size
        img.save(str(path), "JPEG", quality=65, optimize=True)
        return path
    except Exception as exc:
        raise RuntimeError(f"Screenshot failed: {exc}") from exc

def _extract_json(raw: str):
    """
    Extract JSON object from model output.
    Handles markdown fences, extra text, and invisible chars.
    """
    raw = raw.strip()

    # Remove invisible BOM chars
    raw = raw.replace("\ufeff", "").strip()

    # Remove markdown ```json fences
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            cleaned = part.strip()

            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()

            if cleaned.startswith("{"):
                raw = cleaned
                break

    # Extract only the JSON object
    start = raw.find("{")
    end = raw.rfind("}")

    if start != -1 and end != -1:
        raw = raw[start:end+1]

    return json.loads(raw)

def capture_and_analyse(extra_prompt: str = "") -> dict:
    """
    Take a screenshot and ask Puter vision model to analyse the UI.
    Tries each model until one works.
    Returns parsed JSON result.
    """

    try:
        path = _take_screenshot()
    except RuntimeError as exc:
        return {"error": str(exc), "visible_elements": []}

    size_kb = path.stat().st_size // 1024
    print(f"         [vision] screenshot: {path.name} ({size_kb}KB)")

    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")

    user_text = "Analyse this screenshot and return the JSON structure."
    if extra_prompt:
        user_text += f" Context: {extra_prompt}"

    image_message = {
        "role": "user",
        "content": [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}"
                },
            },
            {
                "type": "text",
                "text": user_text,
            },
        ],
    }

    last_error = "No models tried."

    for model in VISION_MODELS:
        for attempt in range(2):
            try:
                client = _puter_client()

                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": VISION_SYSTEM_PROMPT,
                        },
                        image_message,
                    ],
                    max_tokens=1500,
                    temperature=0.1,
                )

                raw = (resp.choices[0].message.content or "").strip()

                result = _extract_json(raw)

                result["_screenshot_path"] = str(path)
                result["_model_used"] = model

                print(f"         [vision] ✓ model={model}")

                return result

            except json.JSONDecodeError as exc:
                raw_preview = locals().get("raw", "")[:300]

                last_error = (
                    f"Invalid JSON from {model}: {exc}. "
                    f"Raw start={raw_preview!r}"
                )

                print(f"         [vision] ✗ {last_error}")

                # retry or move to next model
                continue

            except Exception as exc:
                err_str = str(exc)

                last_error = (
                    f"model={model} attempt={attempt+1}: {err_str}"
                )

                print(
                    f"         [vision] ✗ {last_error[:120]}"
                )

                # bad request: don't waste attempts
                if "400" in err_str:
                    break

                # auth failure: stop
                if "401" in err_str or "403" in err_str:
                    return {
                        "error": f"Puter auth error: {err_str}",
                        "visible_elements": [],
                    }

                if attempt < 1:
                    time.sleep(3)

    return {
        "error": f"All vision models failed. Last: {last_error}",
        "visible_elements": [],
    }


# ── pyautogui-based coordinate actions ───────────────────────────────

def _pyag():
    try:
        import pyautogui
        return pyautogui
    except ImportError:
        raise RuntimeError("pyautogui not installed. Run: pip install pyautogui")


def puter_click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    try:
        pag = _pyag()
        w, h = pag.size()
        x = max(0, min(x, w - 1))
        y = max(0, min(y, h - 1))
        pag.click(x, y, button=button, clicks=clicks, interval=0.1)
        return f"[VISION_CLICK] Clicked ({x}, {y}) × {clicks}"
    except Exception as exc:
        return f"[VISION_CLICK] Failed: {exc}"


def puter_type(text: str) -> str:
    try:
        pag = _pyag()
        if all(ord(c) < 128 for c in text):
            pag.typewrite(text, interval=0.04)
        else:
            try:
                import pyperclip
                pyperclip.copy(text)
            except ImportError:
                import subprocess
                subprocess.run(
                    ["powershell", "-command", "$input | Set-Clipboard"],
                    input=text, text=True, timeout=5, capture_output=True
                )
            pag.hotkey("ctrl", "v")
            time.sleep(0.1)
        return f"[VISION_TYPE] Typed {len(text)} chars"
    except Exception as exc:
        return f"[VISION_TYPE] Failed: {exc}"


def puter_hotkey(*keys: str) -> str:
    try:
        pag = _pyag()
        pag.hotkey(*keys)
        return f"[VISION_HOTKEY] {' + '.join(keys)}"
    except Exception as exc:
        return f"[VISION_HOTKEY] Failed: {exc}"


def puter_scroll(x: int, y: int, amount: int) -> str:
    try:
        pag = _pyag()
        pag.scroll(amount, x=x, y=y)
        direction = "up" if amount > 0 else "down"
        return f"[VISION_SCROLL] Scrolled {direction} ×{abs(amount)} at ({x},{y})"
    except Exception as exc:
        return f"[VISION_SCROLL] Failed: {exc}"


# ── Availability check ────────────────────────────────────────────────
try:
    import pyautogui as _pag_check  # noqa: F401
    _PYAUTOGUI_OK = True
except ImportError:
    _PYAUTOGUI_OK = False

PUTER_AVAILABLE: bool = bool(os.environ.get("PUTER_AUTH_TOKEN")) and _PYAUTOGUI_OK