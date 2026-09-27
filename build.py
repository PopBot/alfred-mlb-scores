#!/usr/bin/env python3
"""
build.py
Packages the MLB Scores Alfred workflow into a clean .alfredworkflow zip archive.
"""
import os
import plistlib
import zipfile

WORKFLOW_DIR = os.path.dirname(os.path.abspath(__file__))
PLIST_FILE = os.path.join(WORKFLOW_DIR, "info.plist")

FILES_TO_INCLUDE = [
    "info.plist",
    "icon.png",
    "mlb.py",
    "mlb_standings.py",
    "mlb_player.py",
    "mlb_team.py",
    "utils.py",
    "image_utils.py",
    "requirements.txt",
    "README.md",
]

DIRS_TO_INCLUDE = [
    "data",
    "mlb_logos",
    "lib",
]

EXCLUDE_EXTENSIONS = {".pyc", ".DS_Store"}
EXCLUDE_DIRS = {"__pycache__", ".cache", ".git"}


def build():
    # Read version from info.plist if present
    version = "1.0.0"
    if os.path.exists(PLIST_FILE):
        try:
            with open(PLIST_FILE, "rb") as f:
                plist = plistlib.load(f)
                version = plist.get("version", version)
        except Exception:
            pass

    out_names = [
        "MLB_Workflow_V1.alfredworkflow",
        "mlb-scores.alfredworkflow",
    ]

    for out_name in out_names:
        out_path = os.path.join(WORKFLOW_DIR, out_name)
        if os.path.exists(out_path):
            os.remove(out_path)

        print(f"Building {out_name} (v{version})...")
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            for item in FILES_TO_INCLUDE:
                item_path = os.path.join(WORKFLOW_DIR, item)
                if os.path.exists(item_path):
                    z.write(item_path, arcname=item)
                else:
                    print(f"Warning: {item} not found")

            for dir_name in DIRS_TO_INCLUDE:
                dir_path = os.path.join(WORKFLOW_DIR, dir_name)
                if not os.path.exists(dir_path):
                    continue
                for root, dirs, files in os.walk(dir_path):
                    # Filter out unwanted directories
                    dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                    for file in files:
                        if file in EXCLUDE_EXTENSIONS or any(file.endswith(ext) for ext in EXCLUDE_EXTENSIONS):
                            continue
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, WORKFLOW_DIR)
                        z.write(full_path, arcname=rel_path)

        size_kb = os.path.getsize(out_path) / 1024
        print(f"Successfully packaged {out_name} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    build()
