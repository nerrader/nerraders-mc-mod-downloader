import requests
from os import makedirs
import json
from sys import exit
import constants as const

# global constants
print = const.CONSOLE.print

# APPDATA_FILEPATH is where program stores json files


def is_modrinth_up() -> bool:
    """checks if your internet connection is up and if modrinth api servers are down, if not allows
    you access to the rest of the program

    Returns:
        bool: True if you have sufficient internet connection and modrinth servers arent down, else False
        True: allow continuation of the builder.py process
        False: immediately exit the program
    """
    try:
        staging_api_url = "https://staging-api.modrinth.com"
        response = requests.get(staging_api_url, timeout=const.API_TIMEOUT)
        response.raise_for_status()
        return True
    except Exception:
        print(
            "There was a problem connecting to Modrinth API Servers",
            style="error",
        )
        return False


def get_mods_json() -> bool:
    """grabs the mods.json from my github repo, and puts it in mods.json (locally on appdata/roaming)

    Raises:
        requests.exceptions.HTTPError: If response.status_code is not 200 (success) or 304 (mods.json using latest version),
        this is either a server error (github issues) or a cilent error (internet issues)

    Returns:
        bool: it determines whether the slugsidmap.json gets should updated or not (aka if slugidmap() gets called or not)
    """
    etag_filepath = const.APPDATA_FILEPATH / "mods.etag"
    mods_url = "https://raw.githubusercontent.com/nerrader/nerraders-mc-mod-downloader/refs/heads/main/data/mods.json"
    api_headers = {}
    if etag_filepath.exists():
        api_headers["If-None-Match"] = etag_filepath.read_text().strip()
    response = requests.get(mods_url, headers=api_headers, timeout=const.API_TIMEOUT)
    if response.status_code == 304:
        print("mods.json is already on the latest version.")
        return False
    elif response.status_code != 200:
        raise requests.exceptions.HTTPError(
            f"CRITICAL ERROR: Could not connect to mod list, github API responded with status {response.status_code}"
        )
    data = response.json()

    with open(const.MODS_FILEPATH, "w") as file:
        json.dump(data, file, indent=4)
    if "ETag" in response.headers:
        with open(etag_filepath, "w") as file:
            etag_filepath.write_text(response.headers["ETag"])
    print("Successfully made mods.json")
    return True


def get_slugslist() -> list[str]:  # only slugs, no ids
    """Summary:
    Gets the list of slugs (value) from the mods.json

    Returns:
        list[str]: The list of slugs
    """
    slugslist: list[str] = []
    with open(const.MODS_FILEPATH) as file:
        modslist = json.load(file)
        for category, category_mods in modslist.items():
            if category == "library_mods":
                for mod in category_mods:
                    slugslist.append(mod)
            else:
                for mod in category_mods:
                    slugslist.append(mod.get("value", mod))
        return slugslist


def modify_slugsmap(slugslist: list[str]) -> None:
    """Summary:
    From the list of slugs given, use the modrinth API to find the IDs for each slug,
    then put it in a dictionary (id: slug), then saves it to a file called idslugmap.json (locally in appdata)

    idslugmap.json will be used to convert slugs into ids and vice versa in main.py

    Args:
        slugslist (list[str]): The list of slugs that will be needed to find the IDs of each, usually from
        getslugslist()
    """
    idslugmap: dict = {}
    API_URL = "https://api.modrinth.com/v2/projects"
    api_params = {"ids": json.dumps(slugslist)}
    response = requests.get(API_URL, params=api_params, timeout=const.API_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    for mod in data:
        idslugmap[mod["id"]] = mod["slug"]  # for mod in data
    with open(const.IDSLUGMAP_FILEPATH, "w") as file:
        json.dump(idslugmap, file, indent=4)
    print("Successfully made idslugmap.json")


def get_slugsidmap() -> None:
    """combines two functions, to make a single function which handles the entire slugidmap creation"""
    modify_slugsmap(get_slugslist())


def get_default_config() -> dict:
    """it generates a default config for those who dont have a config.json yet
    then saves them into config.json"""
    api_url = "https://api.modrinth.com/v2/tag/game_version"
    data = requests.get(
        api_url, timeout=const.API_TIMEOUT
    ).json()  # pretty much guaranteed to succeed unless bad internet or server crash
    minecraft_versions = [
        version["version"] for version in data if version["version_type"] == "release"
    ]
    latest_minecraft_version = minecraft_versions[0]
    default_config = {
        "version": latest_minecraft_version,
        "mod_loader": "fabric",
        "valid_versions": ["release"],
        "mods_directory": "",
        "behaviour_settings": {
            "auto_clear_jars": False,
            "show_detailed_logs": False,
        },
    }
    return default_config


def save_config(config: dict) -> None:
    """saves the config

    Args:
        config (dict): the config that you want to save
    """
    with open(const.CONFIG_FILEPATH, "w") as file:
        file.dump(config)


def main() -> tuple[dict]:
    if not is_modrinth_up():
        print(
            "either your internet connection is down, or modrinth servers arent up. try again next time",
            style="error",
        )
        input("")
        exit(0)

    makedirs(const.APPDATA_FILEPATH, exist_ok=True)
    # checks if config.json is real
    try:
        with open(const.CONFIG_FILEPATH) as file:
            json.load(file)  # will raise an error if empty, and also if doesnt exist
    except (json.JSONDecodeError, FileNotFoundError):
        print("Could not load config.json, setting to defaults")
        save_config(get_default_config())

    try:
        should_update_idslugmap = (
            get_mods_json()
        )  # returns true if needs to be updated, false otherwise

        if should_update_idslugmap or not const.IDSLUGMAP_FILEPATH.exists():
            get_slugsidmap()

    except requests.exceptions.HTTPError as error:
        print(f"Critical Error: {error}")
        exit(1)

    # loading the file contents here cuz why not
    try:
        with open(const.CONFIG_FILEPATH) as file:
            config_json = json.load(file)
        with open(const.IDSLUGMAP_FILEPATH) as file:
            id_slug_map_json = json.load(file)
        with open(const.MODS_FILEPATH) as file:
            mods_json = json.load(file)
        return (mods_json, id_slug_map_json, config_json)
    except Exception as error:
        print(f"Something happened: {error}, resetting files to defaults")
        save_config(get_default_config())
        get_mods_json()
        get_slugsidmap()
        return main()


if __name__ == "__main__":
    main()
