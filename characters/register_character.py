"""
Register a character reference image with the Qwen-Image-2.1 Modal app.

USAGE:
    python register_character.py <name> <image_path>

EXAMPLES:
    python register_character.py Leo leo_clean.png
    python register_character.py Mia mia_clean.png
    python register_character.py Cloud cloud_clean.png
    python register_character.py Lightbulb lightbulb_clean.png
    python register_character.py StickFigure stickfigure_clean.png

No dependencies beyond the Python standard library - nothing to pip install.
Re-running with the same name overwrites that character's stored image.
"""

import sys
import json
import base64
import urllib.request
import urllib.error

ENDPOINT = "https://creatyoasis--qwen-image-2-1-register-character.modal.run"


def main():
    if len(sys.argv) != 3:
        print("Usage: python register_character.py <name> <image_path>")
        sys.exit(1)

    name, path = sys.argv[1], sys.argv[2]

    try:
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        print(f"Could not find file: {path}")
        sys.exit(1)

    payload = json.dumps({"name": name, "image_base64": encoded}).encode()
    req = urllib.request.Request(
        ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as response:
            print(response.read().decode())
            print(f"'{name}' registered successfully.")
    except urllib.error.HTTPError as e:
        print(f"Server error ({e.code}): {e.read().decode()}")
    except urllib.error.URLError as e:
        print(f"Could not reach the endpoint: {e.reason}")


if __name__ == "__main__":
    main()
