import requests
from os import getenv, makedirs
import json
from rich.theme import Theme
from rich.console import Console
from pathlib import Path
from sys import exit

custom_theme = Theme({"error": "bold red", "success": "green", "warning": "yellow"})
console = Console(theme=custom_theme, highlight=False)
print = console.print


def main():
    # where program stores json files
    appdata_filepath = Path(getenv("APPDATA")) / "mc-mods-downloader"
    makedirs(appdata_filepath, exist_ok=True)

    mods_filepath = appdata_filepath / "mods.json"
    idslugmap_filepath = appdata_filepath / "idslugmap.json"
    config_filepath = appdata_filepath / "config.json"

    def get_mods_json() -> bool:
        """grabs the mods.json from my github repo, and puts it in mods.json (locally on appdata)

        Raises:
            requests.exceptions.HTTPError: if response.status_code is not 304 (when etag matches aka not modified),
            this can either mean they have no internet connection or the servers are down

        Returns:
            bool: it determines whether the slugsidmap.json gets updated or not
        """
        etag_filepath = appdata_filepath / "mods.etag"
        mods_url = "https://raw.githubusercontent.com/nerrader/nerraders-mc-mod-downloader/refs/heads/main/data/mods.json"
        api_headers = {}
        if etag_filepath.exists():
            api_headers["If-None-Match"] = etag_filepath.read_text().strip()
        response = requests.get(mods_url, headers=api_headers, timeout=5)
        if response.status_code == 304:
            print("mods.json is already on the latest version.")
            return False
        elif response.status_code != 200:
            raise requests.exceptions.HTTPError(
                f"CRITICAL ERROR: Could not connect to mod list, github API responded with status {response.status_code}"
            )
        data = response.json()

        with open(mods_filepath, "w") as file:
            json.dump(data, file, indent=4)
        if "ETag" in response.headers:
            with open(etag_filepath, "w") as file:
                etag_filepath.write_text(response.headers["ETag"])
        print("Successfully made mods.json")
        return True

    def get_slugslist() -> list[str]:  # only slugs, no ids
        """Summary:
        Gets the list of slugs from the mods.json

        Returns:
            list[str]: The list of slugs
        """
        slugslist: list[str] = []
        with open(mods_filepath) as file:
            modslist = json.load(file)
            for (
                category
            ) in modslist.values():  # for category in modslist, for mod in category
                for mod in category:
                    slugslist.append(mod["value"])
        return slugslist

    # this gets the ids according to slugs and puts them in a dictionary (map)
    def modify_slugsmap(slugslist: list[str]) -> None:
        """Summary:
        From the list of slugs given, use the modrinth API to find the IDs for each slug,
        then put it in a dictionary (id: slug), then saves it to a file called idslugmap.json

        Args:
            slugslist (list[str]): The list of slugs that will be needed to find the IDs of each
        """
        idslugmap = {}
        api_url = "https://api.modrinth.com/v2/projects"
        api_params = {"ids": json.dumps(slugslist)}
        response = requests.get(api_url, params=api_params)
        response.raise_for_status()
        data = response.json()
        for mod in data:
            idslugmap[mod["id"]] = mod["slug"]  # for mod in data
        with open(idslugmap_filepath, "w") as file:
            json.dump(idslugmap, file, indent=4)
        print("Successfully made idslugmap.json")

    def get_slugsidmap() -> None:
        """combines two functions, to make a single function which handles the entire slugidmap creation"""
        modify_slugsmap(get_slugslist())

    def get_configs() -> None:
        """it generates a default config for those who dont have a config.json yet"""
        default_config = {
            "version": "1.21.11",
            "mod_loader": "fabric",
            "valid_versions": ["release"],
            "mods_directory": "",
            "auto_clear_jars": False,
            "show_deatiled_logs": False,
        }
        with open(config_filepath, "w") as file:
            json.dump(default_config, file, indent=4)

    try:
        with open(config_filepath) as file:
            json.load(file)  # will raise an error if empty, and also if doesnt exist
    except (json.JSONDecodeError, FileNotFoundError):
        print("Could not load config.json, setting to defaults")
        get_configs()

    try:
        should_update_idslugmap = (
            get_mods_json()
        )  # returns true if needs to be updated, false otherwise

        if should_update_idslugmap or not idslugmap_filepath.exists():
            get_slugsidmap()

    except requests.exceptions.HTTPError as error:
        print(f"Critical Error: {error}")
        exit(1)


if __name__ == "__main__":
    main()
