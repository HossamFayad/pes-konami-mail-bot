import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add current dir to python path
sys.path.append(os.path.dirname(__file__))

from bot import start_bot

if __name__ == "__main__":
    try:
        start_bot()
    except KeyboardInterrupt:
        print("\n[!] Bot stopped gracefully.")

