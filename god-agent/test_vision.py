"""
test_vision.py — Run this directly to verify Puter AI vision is working.

Usage:
    python test_vision.py

What it does:
    1. Takes a screenshot of your screen
    2. Sends it to each Puter model in order
    3. Prints exactly what comes back (full response + any errors)
    4. Tells you which model works

If this script works, the agent's vision will work.
If it fails, you'll see the exact error from Puter's API.
"""
import os, sys, base64, json, time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import find_dotenv, load_dotenv
load_dotenv(find_dotenv())

PUTER_BASE_URL = "https://api.puter.com/puterai/openai/v1/"
MODELS = ["claude-sonnet-4-5", "gpt-4o", "google/gemini-2.5-flash"]

token = os.environ.get("PUTER_AUTH_TOKEN", "")
if not token:
    print("❌ PUTER_AUTH_TOKEN not set in .env")
    sys.exit(1)
print(f"✓ PUTER_AUTH_TOKEN found ({len(token)} chars)")

# Take screenshot
print("\n[1] Taking screenshot...")
try:
    import pyautogui
    from PIL import Image
    img = pyautogui.screenshot()
    w, h = img.size
    ratio = 1024 / w
    img = img.resize((1024, int(h * ratio)), Image.LANCZOS)
    path = Path("test_screenshot.jpg")
    img.save(str(path), "JPEG", quality=65, optimize=True)
    size_kb = path.stat().st_size // 1024
    print(f"✓ Screenshot saved: {path} ({size_kb}KB, {1024}x{int(h*ratio)})")
except Exception as e:
    print(f"❌ Screenshot failed: {e}")
    sys.exit(1)

b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
print(f"✓ Base64 encoded: {len(b64)} chars")

# Try each model
from openai import OpenAI
client = OpenAI(api_key=token, base_url=PUTER_BASE_URL)

SYSTEM = "You are a GUI analyser. Respond with ONLY valid JSON: {\"screen_state\": \"one line description\", \"visible_elements\": []}"

for model in MODELS:
    print(f"\n[2] Trying model: {model}")
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": "What is on this screen? Return JSON only."}
                ]}
            ],
            max_tokens=500,
            temperature=0.1,
        )
        raw = resp.choices[0].message.content or ""
        print(f"✓ SUCCESS with {model}")
        print(f"  Response: {raw[:300]}")
        print(f"\n✅ Vision is working! Use model: {model}")
        sys.exit(0)
    except Exception as exc:
        # Print FULL error — no truncation
        print(f"❌ FAILED: {type(exc).__name__}: {exc}")
        # If it's an API error, try to get the full body
        if hasattr(exc, 'response') and exc.response is not None:
            try:
                print(f"   Full response body: {exc.response.text}")
            except:
                pass
        if hasattr(exc, 'body'):
            print(f"   Error body: {exc.body}")

print("\n❌ ALL MODELS FAILED. Vision will not work.")
print("Check the errors above to diagnose the issue.")

resp = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[
        {
            "role": "user",
            "content": "Say hello"
        }
    ]
)