import requests
import json
from pathlib import Path
from os import getenv, makedirs


def main():
    appdata_filepath = Path(getenv("APPDATA")) / "mc-mods-downloader"
    makedirs(appdata_filepath, exist_ok=True)

    mods_filepath = appdata_filepath / "mods.json"
    idslugmap_filepath = appdata_filepath / "idslugmap.json"
    # if mods.json exists: check version file, if outdated downlaod from github
    # if doesnt exist: downlaod from github
    # if idslugmap.json exists: if you downloaded a new version of mods.json: redo creation
    # if doesnt exist: do creation

    def get_mods_json():
        pass

    def get_slugslist() -> set[str]:  # only slugs, no ids
        """Summary:
        Gets the list of slugs from the mods.json

        Returns:
            list[str]: The list of slugs
        """
        slugslist = set()
        with open(mods_filepath) as file:
            modslist = json.load(file)
            for (
                category
            ) in modslist.values():  # for category in modslist, for mod in category
                for mod in category:
                    slugslist.add(mod["value"])
        return slugslist

    # this gets the ids according to slugs and puts them in a dictionary (map)
    def modify_slugsmap(slugslist: set[str]) -> None:
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
        if response.status_code != 200:
            print("somethings up")
            print(response.status_code)
        data = response.json()
        for mod in data:
            idslugmap[mod["id"]] = mod["slug"]  # for mod in data
        with open(idslugmap_filepath, "w") as file:
            json.dump(idslugmap, file, indent=4)

    def get_slugsidmap():
        modify_slugsmap(get_slugslist())

    if not mods_filepath.exists():
        get_mods_json()

    if not idslugmap_filepath.exists():
        get_slugsidmap()


if __name__ == "__main__":
    main()
