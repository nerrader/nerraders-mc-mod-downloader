import requests
from glob import glob
import os
import sys
import questionary
import json
from rich.theme import Theme
from rich.console import Console
import builder
from pathlib import Path

custom_theme = Theme({"error": "bold red", "success": "green", "warning": "yellow"})
console = Console(theme=custom_theme, highlight=False)
print = console.print

appdata_filepath = appdata_filepath = (
    Path(os.getenv("APPDATA") or (Path.home() / "AppData" / "Roaming"))
) / "mc-mods-downloader"

mods_filepath = appdata_filepath / "mods.json"
idslugmap_filepath = appdata_filepath / "idslugmap.json"
config_filepath = appdata_filepath / "config.json"

visited_mod_ids: set[str] = set()


def choose_mods() -> list:
    initial_modlist: list[str] = []
    with open(mods_filepath) as file:
        json_modlist_data = json.load(file)

    category_map = {
        "Optimization & Performance": "optimization_mods",
        "PVP & Combat": "pvp_mods",
        "Miscellaneous": "misc_mods",
        "Building": "building_mods",
        "Visuals & Aesthetics": "visual_mods",
        "Interfaces & Utility": "interface_mods",
        "Finish & Download": "exit and save",
        "Clear Modlist": "clear",
        "Exit & Cancel": "cancel",
    }

    while True:
        category_choice = questionary.select(
            "Choose a category to browse mods", choices=(list(category_map.keys()))
        ).ask()
        json_key = category_map[category_choice]

        if json_key == "exit and save":
            return initial_modlist
        elif json_key == "clear":
            initial_modlist = []
            continue
        elif json_key == "cancel":
            sys.exit(0)

        mods_in_category = json_modlist_data.get(json_key, [])

        mod_choices = [
            {
                "name": mod["name"],
                "value": mod["value"],
                "checked": mod["value"] in initial_modlist,
            }
            for mod in mods_in_category
        ]

        selection = questionary.checkbox(
            message=f"Select mods from {category_choice}", choices=mod_choices
        ).ask()

        # dont know how this works but it does, dont touch it

        initial_modlist = [
            mod
            for mod in initial_modlist
            if mod not in [mod["value"] for mod in mods_in_category]
        ]
        if selection is not None:
            initial_modlist += selection


def slug_to_id(target_slug: str) -> str:
    id = next(
        (id for id, slug in id_to_slug_map.items() if slug == target_slug),
    )
    if id is None:
        print("yeah so the slug_to_id function mightve broken", style="error")
    return id


def get_mods(slugorid: str, is_dependency=False) -> None:
    loaders = modpack_config.get("mod_loader", "fabric")
    version = modpack_config["version"]
    valid_versions = modpack_config.get("valid_versions", "release")
    # for dependencies the "slug" is an id
    if is_dependency:
        id = slugorid
        slug = id_to_slug_map[id]
    # turn everything into an id for consistency
    else:
        id = slug_to_id(slugorid)
        slug = slugorid
    # so we dont have to do an api call if weve done the mod before
    if not id or id in visited_mod_ids:
        return

    visited_mod_ids.add(id)
    print(f"visiting mod: {slug} {'(dependency)' if is_dependency else ''}")
    # put id in instead for consistency, slugs can change while ids cant
    api_url = f"https://api.modrinth.com/v2/project/{id}/version"
    api_params = {
        "loaders": f'["{loaders.lower()}"]',
        "game_versions": f'["{version}"]',
        "include_changelog": "false",
    }
    response = requests.get(api_url, params=api_params)
    data = response.json()
    if response.status_code != 200:
        print(
            f"Something wrong happened, status code: {response.status_code}",
            style="error",
        )
        failed_mods.append(slug)
        return
    elif len(data) == 0:
        print(
            f"No files for fabric game version 1.21.11 found in mod {slug}",
            style="error",
        )
        failed_mods.append(slug)
        return

    latest_version = [  # filters out all versions not allowed in valid versions (usually alpha/beta versions)
        version for version in data if version.get("version_type") in valid_versions
    ]

    if not latest_version:
        print(
            f"Mod {slug} has no versions with {valid_versions} releases", style="error"
        )
        failed_mods.append(slug)
        return
    latest_version = latest_version[0]  # the actual latest version

    target_file = next(  # look at files, find the latest one that is a primary file
        (file for file in latest_version.get("files", []) if file.get("primary")),
        latest_version["files"][0],
    )
    target_filename = target_file["filename"]
    target_url = target_file["url"]

    if not target_filename or not target_url:
        print(
            f"somethings up with the latest version url and filename of mod {slug}",
            style="error",
        )
        failed_mods.append(slug)
        return
    mod_data = {
        "slug": slug,
        "filename": target_filename,
        "url": target_url,
    }
    full_modlist.append(mod_data)
    if is_dependency:
        dependency_mods_downloaded.append(slug)
    # it is a dependency, visual jukebox forgot to add the polymer in their dependencies
    if slug == "visual-jukebox":
        get_mods("polymer")
    dependencies = [
        dependency
        for dependency in latest_version.get("dependencies", [])
        if dependency.get("dependency_type") == "required"
    ]
    if dependencies:
        for dependency in dependencies:
            try:
                dependency_project_id = dependency.get("project_id")
                if dependency_project_id not in visited_mod_ids:
                    get_mods(dependency_project_id, is_dependency=True)
            except Exception as error:
                print(
                    f"\nHey, you should probably download this dependency yourself cuz the script couldnt do it: {repr(error)} ERROR",
                    style="warning",
                )
                print(
                    f"Link: https://modrinth.com/mod/{dependency_project_id}",
                    style="warning",
                )


def clear_jar_files(directory_path: str) -> None:
    files = glob(os.path.join(directory_path, "*.jar"))
    for file in files:
        try:
            os.remove(file)
        except Exception as error:
            print(f"Could not remove {file}: {error}", style="error")


def download_mods(modlist: list[dict[str, str]]) -> None:
    modpack_name = modpack_config.get("name", "Default")
    folder_path = (
        rf"C:\Users\darre\AppData\Roaming\.minecraft\modpacks\{modpack_name}\mods"
    )
    clear_folder = questionary.confirm(
        "Should we delete all .jar files in the minecraft mods folder path to remove duplicates? (RECOMMENDED)"
    ).ask()
    if clear_folder:
        clear_jar_files(folder_path)
        print("Everything cleared.", style="success")
    for target_mod in modlist:
        download_path = os.path.join(folder_path, target_mod["filename"])

        url = target_mod.get("url")
        if not url:
            print(f"{target_mod} has no url!")
            return

        print(f"downloading {target_mod.get('filename', 'mod_filename')}")

        response = requests.get(url, stream=True)
        response.raise_for_status()

        with open(download_path, "wb") as file:
            for chunk in response.iter_content(
                chunk_size=8192
            ):  # idk what tf this does but it works according to google so
                file.write(chunk)

        print("download complete", style="success")


if __name__ == "__main__":
    with open(config_filepath) as file:
        modpack_config = json.load(file)
    full_modlist: list[dict[str, str]] = []
    failed_mods: list[str] = []
    dependency_mods_downloaded: list[str] = []
    with open(idslugmap_filepath) as file:
        id_to_slug_map: dict[str, str] = json.load(file)
    if len(sys.argv) > 1:
        if sys.argv[1] == "cli":
            initial_modlist = sys.argv[2:]
    else:
        initial_modlist = choose_mods()
    for mod in initial_modlist:
        get_mods(mod)  # automatically appends to full_modlist
    download_mods(full_modlist)
    print(
        f"\n[green]{len(full_modlist)} mods downloaded![/green] ({len(dependency_mods_downloaded)} of which were dependencies)"
    )
    if len(failed_mods) > 0:
        print(
            f"{len(failed_mods)} mods failed to download: {failed_mods}", style="error"
        )
    print("")
