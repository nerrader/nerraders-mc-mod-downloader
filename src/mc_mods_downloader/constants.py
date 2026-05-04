# This file is only for storing constants in main.py and builder.py
from pathlib import Path
import sys
from threading import Lock

from platformdirs import PlatformDirs, user_data_path
from rich.theme import Theme
from rich.console import Console

# rich module things
CUSTOM_THEME = Theme({"error": "bold red", "success": "green", "warning": "yellow"})
CONSOLE = Console(theme=CUSTOM_THEME, highlight=False)

# APPDATA_FILEPATH is where program stores json files
# filepaths
_dirs = PlatformDirs("mc-mods-downloader", appauthor="nerrader", roaming=True)

MAIN_DATA_FILEPATH: Path = _dirs.user_data_path
MODS_FILEPATH: Path = MAIN_DATA_FILEPATH / "mods.json"
IDSLUGMAP_FILEPATH: Path = MAIN_DATA_FILEPATH / "idslugmap.json"
CONFIG_FILEPATH: Path = MAIN_DATA_FILEPATH / "config.json"
# for finding the folder path automatically

USER_OS: str = sys.platform
HOME_FILEPATH = Path.home()
APPDATA_FILEPATH: Path = user_data_path(roaming=True)
# OTHER CONSTANTS

# specifically for one thing in main.py:get_mods()
# aka for adding mods in the visited_mods set
THREADING_LOCK = Lock()

# for downloading mods (used in main.py:download_mods())
CHUNK_SIZE = 16384

# for every api request
API_TIMEOUT = 10
USER_AGENT = "https://github.com/nerrader/nerraders-mc-mod-downloader"
