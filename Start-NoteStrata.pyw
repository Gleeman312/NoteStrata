from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
ERROR_LOG = APP_DIR / "startup-error.log"


def run() -> None:
    # File associations can start a script with an unrelated working directory.
    # Always make imports and data paths resolve from the NoteStrata folder.
    os.chdir(APP_DIR)
    sys.path.insert(0, str(APP_DIR))
    from app import main

    main()


if __name__ == "__main__":
    try:
        run()
    except Exception:
        ERROR_LOG.write_text(traceback.format_exc(), encoding="utf-8")
