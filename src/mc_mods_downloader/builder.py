import json
from typing import Any

from loguru import logger
import requests

from mc_mods_downloader import constants as const, storage

print = const.CONSOLE.print


def _get_mods_json(api_session: requests.Session) -> bool:
    """Synchronizes the local mods.json with the remote GitHub repository.

    Raises:
        requests.exceptions.HTTPError: If server responds with a status code
        other than 200 or 304.

    Returns:
        bool: True if a fresh file was downloaded and written to disk, signaling
        that downstream cache maps (like slug-to-ID mappings) must be rebuilt.
        False if the local file is already up to date.
    """
    logger.info("Getting the mods.json")

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
    logger.success("Successfully made mods.json")
    return True


def _get_slugslist() -> list[str]:
    """Summary:
    Gets the list of slugs (value) from the mods.json

    Returns:
        list[str]: The list of slugs
    """
    logger.info("Getting the slugslist from mods.json")
    slugslist: list[str] = []
    modslist: dict[str, Any] = storage.load_json(const.MODS_FILEPATH)

    for category_mods in modslist.values():
        slugslist.extend(
            [mod["value"] if isinstance(mod, dict) else mod for mod in category_mods]
        )
    return slugslist


def _modify_slugsmap(slugslist: list[str], api_session: requests.Session) -> None:
    """
    From the list of slugs given, use the modrinth API to find the IDs for each slug,
    then put it in a dictionary (id: slug), then saves it to idslugmap.json

    idslugmap.json will be used to convert slugs into ids and vice versa in main.py
    """
    logger.info("Modifying the idslugmap")

    try:
        id_slug_map: dict = {}
        API_URL = "https://api.modrinth.com/v2/projects"
        api_params = {"ids": json.dumps(slugslist)}
        response = api_session.get(
            API_URL, params=api_params, timeout=const.API_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()

        id_slug_map = {mod["id"]: mod["slug"] for mod in data}
        with open(const.IDSLUGMAP_FILEPATH, "w") as file:
            json.dump(id_slug_map, file, indent=4)

        logger.success("Successfully made idslugmap.json")
    except requests.HTTPError as error:
        logger.error(f"HTTP error occurred: {repr(error)}")


def _get_slugsidmap(api_session: requests.Session) -> None:
    """Combines two functions to make a single function which handles the entire slugidmap.json creation"""
    _modify_slugsmap(_get_slugslist(), api_session)


def _checkup_files(api_session: requests.Session) -> None:
    """checks up on the config and idslugmap json files, resets them to defaults if somethings wrong
    updates the idslugmap.json if mods.json is updated/changed

    Args:
        api_session (requests.Session): The API session object, used to pass into the functions used in this function
        that do need an api session

        (technically none of these do, but it does optimize performance)
    """
    logger.info("Checking up on config and idslugmap json files")
    # idslugmap.json checkup, should update or not
    try:
        should_update_idslugmap = _get_mods_json(api_session)

        if should_update_idslugmap or not const.IDSLUGMAP_FILEPATH.exists():
            _get_slugsidmap(api_session)
    except requests.exceptions.RequestException as error:
        logger.critical(f"Error during file checkup: {repr(error)}")
        print(f"Critical Error: {str(error)}", style="error")
        print(
            "\nThis was either caused by the server or the client, maybe check your internet connection",
            style="error",
        )
        raise SystemExit(
            "The app cannot continue due to the above error, exiting now"
        ) from error


def main() -> tuple[dict[str, Any], dict[str, Any]]:
    const.MAIN_DATA_FILEPATH.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        session.headers.update({"User-Agent": const.USER_AGENT})
        while True:
            _checkup_files(session)
            # loading the file contents for returning
            try:
                mods = storage.load_json(const.MODS_FILEPATH)
                idslugmap = storage.load_json(const.IDSLUGMAP_FILEPATH)

                return (mods, idslugmap)
            except Exception as error:
                print(f"Something happened: {error}, resetting files to defaults")
                logger.critical(
                    f"Error during file loading: {repr(error)}. Resetting config and data files to defaults."
                )
                _get_mods_json(session)
                _get_slugsidmap(session)


if __name__ == "__main__":
    main()
