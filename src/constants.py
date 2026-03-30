# This file is only for storing constants in main.py and builder.py
from rich.theme import Theme
from rich.console import Console
from pathlib import Path
from os import getenv
from threading import Lock

# rich module things
CUSTOM_THEME = Theme({"error": "bold red", "success": "green", "warning": "yellow"})
CONSOLE = Console(theme=CUSTOM_THEME, highlight=False)

# APPDATA_FILEPATH is where program stores json files
# filepaths
APPDATA_FILEPATH = (
    Path(getenv("APPDATA")) or Path.home() / "AppData" / "Roaming"
) / "mc-mods-downloader"
MODS_FILEPATH = APPDATA_FILEPATH / "mods.json"
IDSLUGMAP_FILEPATH = APPDATA_FILEPATH / "idslugmap.json"
CONFIG_FILEPATH = APPDATA_FILEPATH / "config.json"


# MISC CONSTANTS

# specifically for one thing in main.py:get_mods()
# aka for adding mods in the visited_mods set
THREADING_LOCK = Lock()

# for downloading mods (used in main.py:download_mods())
CHUNK_SIZE = 16384

# for every api request
API_TIMEOUT = 10
