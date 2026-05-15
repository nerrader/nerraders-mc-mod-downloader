import json
from typing import Any

import requests

from mc_mods_downloader import constants as const, config, storage

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

    storage.write_json(const.MODS_FILEPATH, data)
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
    modslist = storage.load_json(const.MODS_FILEPATH)
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
        storage.load_json(const.CONFIG_FILEPATH)
        # with open(const.CONFIG_FILEPATH) as file:
        #     json.load(file)  # will raise an error if empty, and also if doesnt exist
    except (json.decoder.JSONDecodeError, FileNotFoundError):
        print("Could not load config.json, setting to defaults")
        config.get_default_config(api_session).save_configs()

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


def main() -> tuple[dict[str, Any], dict[str, Any], config.Config]:
    const.MAIN_DATA_FILEPATH.mkdir(parents=True, exist_ok=True)
    # checks if config.json is real
    with requests.Session() as session:
        session.headers.update({"User-Agent": const.USER_AGENT})
        while True:
            checkup_files(session)
            # loading the file contents for returning
            try:
                mods = storage.load_json(const.MODS_FILEPATH)
                idslugmap = storage.load_json(const.IDSLUGMAP_FILEPATH)
                configs = config.Config.load_configs()

                return (mods, idslugmap, configs)
            except Exception as error:
                print(f"Something happened: {error}, resetting files to defaults")
                config.get_default_config().save_configs()
                get_mods_json(session)
                get_slugsidmap(session)


if __name__ == "__main__":
    main()
