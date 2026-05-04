import json
from os import makedirs
from typing import Any

import requests

from mc_mods_downloader import constants as const

# global constants
print = const.CONSOLE.print

# MAIN_DATA_FILEPATH is where program stores json files


def get_mods_json(api_session: requests.Session) -> bool:
    """grabs the mods.json from my github repo, and puts it in mods.json (locally on appdata/roaming)
    also uses mods.etag to check if it is already up to date, removing the need to actually like save it
    every time the app launches

    Raises:
        requests.exceptions.HTTPError: If response.status_code is not 200 (success) or 304 (mods.json using latest version),
        this is either a server error (github issues) or a cilent error (internet issues)

    Returns:
        bool: it determines whether the slugsidmap.json gets should updated or not (aka if slugidmap() gets called or not)
    """
    etag_filepath = const.MAIN_DATA_FILEPATH / "mods.etag"
    mods_url = "https://raw.githubusercontent.com/nerrader/nerraders-mc-mod-downloader/refs/heads/main/data/mods.json"
    api_headers = {}
    if etag_filepath.exists():
        api_headers["If-None-Match"] = etag_filepath.read_text().strip()
    response = api_session.get(mods_url, headers=api_headers, timeout=const.API_TIMEOUT)
    if response.status_code == 304:
        return False
    elif response.status_code != 200:
        raise requests.exceptions.HTTPError(
            f"CRITICAL ERROR: Could not connect to mod list, github API responded with status {response.status_code}"
        )
    data = response.json()

    with open(const.MODS_FILEPATH, "w") as file:
        json.dump(data, file, indent=4)
    if "ETag" in response.headers:
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


def modify_slugsmap(slugslist: list[str], api_session: requests.Session) -> None:
    """Summary:
    From the list of slugs given, use the modrinth API to find the IDs for each slug,
    then put it in a dictionary (id: slug), then saves it to a file called id_slug_map.json (locally in appdata)

    id_slug_map.json will be used to convert slugs into ids and vice versa in main.py

    Args:
        slugslist (list[str]): The list of slugs that will be needed to find the IDs of each, usually from
        getslugslist()
    """
    id_slug_map: dict = {}
    API_URL = "https://api.modrinth.com/v2/projects"
    api_params = {"ids": json.dumps(slugslist)}
    response = api_session.get(API_URL, params=api_params, timeout=const.API_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    id_slug_map = {mod["id"]: mod["slug"] for mod in data}
    with open(const.IDSLUGMAP_FILEPATH, "w") as file:
        json.dump(id_slug_map, file, indent=4)
    print("Successfully made idslugmap.json")


def get_slugsidmap(api_session: requests.Session) -> None:
    """combines two functions, to make a single function which handles the entire slugidmap creation"""
    modify_slugsmap(get_slugslist(), api_session)


def get_default_config(api_session: requests.Session | None = None) -> dict:
    """it generates a default config for those who dont have a config.json yet,

    params:
    api_session: a requests.Session object which is used to optimize performance, if none is
    given, use the regular requests.get() function

    returns:
    dict: the default_config returned, usually passed into save_config() to save it

    uses modrinth api to get the latest minecraft version for the version property"""
    api_url = "https://api.modrinth.com/v2/tag/game_version"
    requests_session = api_session or requests
    headers = {"User-Agent": const.USER_AGENT} if not api_session else None
    data = requests_session.get(
        api_url, timeout=const.API_TIMEOUT, headers=headers
    ).json()
    # pretty much guaranteed to succeed unless bad internet or server crash, so no try except
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
        json.dump(config, file, indent=4)


def checkup_files(api_session: requests.Session) -> None:
    """checks up on the config and idslugmap json files, resets them to defaults if somethings wrong
    updates the idslugmap.json if mods.json is updated/changed

    Args:
        api_session (requests.Session): The API session object, used to pass into the functions used in this function
        that do need an api session

        (technically none of these do, but it does optimize performance)
    """
    # config.json checkup
    try:
        with open(const.CONFIG_FILEPATH) as file:
            json.load(file)  # will raise an error if empty, and also if doesnt exist
    except (json.JSONDecodeError, FileNotFoundError):
        print("Could not load config.json, setting to defaults")
        save_config(get_default_config(api_session))

    # idslugmap.json checkup, should update or not
    try:
        should_update_idslugmap = get_mods_json(
            api_session
        )  # returns true if needs to be updated, false otherwise

        if should_update_idslugmap or not const.IDSLUGMAP_FILEPATH.exists():
            get_slugsidmap(api_session)
    except requests.exceptions.RequestException as error:
        print(f"Critical Error: {str(error)}", style="error")
        print(
            "\nThis was either caused by the server or the client, maybe check your internet connection",
            style="error",
        )
        raise SystemExit(
            "The app cannot continue due to the above error, exiting now"
        ) from error


def main() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:

    makedirs(const.MAIN_DATA_FILEPATH, exist_ok=True)
    # checks if config.json is real
    with requests.Session() as session:
        session.headers.update({"User-Agent": const.USER_AGENT})
        while True:
            checkup_files(session)
            # loading the file contents for returning
            try:
                with (
                    open(const.CONFIG_FILEPATH) as config_json,
                    open(const.IDSLUGMAP_FILEPATH) as idslugmap_json,
                    open(const.MODS_FILEPATH) as mods_json,
                ):
                    return (
                        json.load(mods_json),
                        json.load(idslugmap_json),
                        json.load(config_json),
                    )
            except Exception as error:
                print(f"Something happened: {error}, resetting files to defaults")
                save_config(get_default_config(session))
                get_mods_json(session)
                get_slugsidmap(session)


if __name__ == "__main__":
    main()
