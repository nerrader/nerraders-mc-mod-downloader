import requests
from glob import glob
import os
from sys import exit
import questionary
import json
from rich.theme import Theme
from rich.console import Console, Group
from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    DownloadColumn,
    TaskProgressColumn,
    MofNCompleteColumn,
)
from rich.live import Live
import builder
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

# global variables initialization
# things so the print() works with rich
custom_theme = Theme({"error": "bold red", "success": "green", "warning": "yellow"})
console = Console(theme=custom_theme, highlight=False)
print = console.print

# filepaths
appdata_filepath = appdata_filepath = (
    Path(os.getenv("APPDATA") or (Path.home() / "AppData" / "Roaming"))
) / "mc-mods-downloader"
mods_filepath = appdata_filepath / "mods.json"
idslugmap_filepath = appdata_filepath / "idslugmap.json"
config_filepath = appdata_filepath / "config.json"

# some variables for the thing to work
threading_lock = Lock()
visited_mod_ids: set[str] = set()
full_modlist: list[dict[str, str]] = []
failed_mods: list[str] = []
dependency_mods_downloaded: list[str] = []


def configure_settings(config: dict[str, Any]):
    """configure settings buddy

    Args:
        config (dict[str, Any]): the config to edit, its usually the one in config.json (what else)
    """

    def change_minecraft_version() -> str:
        """uses modrinth api to find the current minecraft game versions, then
        uses a questionary autocomplete prompt to see what the user wants

        Returns:
            str: the game version chosen by the user
        """
        api_url = "https://api.modrinth.com/v2/tag/game_version"
        data = requests.get(api_url).json()  # pretty much guaranteed to be 200
        minecraft_versions = [
            version["version"]
            for version in data
            if version["version_type"] == "release"
        ]
        print("Tip: Press tab to enable autocomplete", style="warning")
        selected_version = questionary.autocomplete(
            "Type your minecraft version (e.g. 1.21): ",
            choices=minecraft_versions,
            default=minecraft_versions[0],  # latest version
        ).ask()
        return selected_version

    def change_mod_loader() -> str:
        """uses questionary to find what mod loader the user wants to choose

        Returns:
            str: the mod loader chosen by the user
        """
        selected_mod_loader = questionary.select(
            "Choose your mod loader:", choices=("Fabric", "NeoForge", "Forge", "Quilt")
        ).ask()
        return selected_mod_loader

    def select_valid_versions() -> list[str]:
        """select which versions of mods are allowed (alpha, beta, release/stable)

        Returns:
            list[str]: selected versions
        """
        selected_valid_versions = questionary.checkbox(
            "Which mod versions do you allow?",
            choices=(
                questionary.Choice(
                    title="Release (Stable)",
                    value="release",
                    checked="release" in config.get("valid_versions", []),
                ),
                questionary.Choice(
                    title="Beta (Testing)",
                    value="beta",
                    checked="beta" in config.get("valid_versions", []),
                ),
                questionary.Choice(
                    title="Alpha (Early Development, NOT RECOMMENDED)",
                    value="alpha",
                    checked="alpha" in config.get("valid_versions", []),
                ),
            ),
            default="release",
        ).ask()
        return selected_valid_versions

    def change_default_path() -> str:
        """change the default path for the modpack download path, changing this will
        remove the prompts to ask for your path during the downloading so it better
        be correct

        Returns:
            str: the selected folder path by the user
        """
        print(
            "Note that changing this setting will remove the pathing prompt when downloading",
            style="warning",
        )
        print(
            "Tip: You can copy and paste the path from the file explorer search bar",
            style="warning",
        )
        selected_folder_path = questionary.path(
            "Change Default Mods Path: (press tab)", default=""
        ).ask()
        return selected_folder_path

    def change_behaviour_settings() -> None:
        """behaviour settings are basically just the true/false value settings
        returns None as the changes happen inside this function directly
        """
        while True:
            behaviour_settings_chioces = (
                questionary.Choice(
                    title=f"Skip .jar files Deletion Confirmation [{config['auto_clear_jars']}]",
                    value="auto_clear_jars",
                ),
                questionary.Choice(
                    title=f"Show Detailed Logs [{config['show_deatiled_logs']}]",
                    value="show_deatiled_logs",
                ),
                questionary.Choice(title="Go Back", value="back"),
            )

            behaviour_settings_selection = questionary.select(
                "Behaviour Settings",
                choices=behaviour_settings_chioces,
                default=None,
            ).ask()
            if (
                behaviour_settings_selection == "back"
                or behaviour_settings_selection is None
            ):
                break
            else:
                config[behaviour_settings_selection] = not config[
                    behaviour_settings_selection
                ]

    def save_config() -> None:
        with open(config_filepath, "w") as file:
            json.dump(config, file, indent=4)
        print("Successfully saved settings", style="success")

    def main() -> None:
        nonlocal config
        while True:
            choice = questionary.select(
                "Settings Menu",
                choices=(
                    "Change Minecraft Version",
                    "Change Mod Loader",
                    "Select Valid Versions",
                    "Set Default Folder Path",
                    "Behaviour Settings",
                    "Reset Settings to Default",
                    "Exit and Save",
                    "Cancel",
                ),
            ).ask()
            match choice:
                case "Change Minecraft Version":
                    config["version"] = change_minecraft_version()
                case "Change Mod Loader":
                    config["mod_loader"] = change_mod_loader()
                case "Select Valid Versions":
                    config["valid_versions"] = select_valid_versions()
                case "Set Default Folder Path":
                    config["mods_directory"] = change_default_path()
                case "Behaviour Settings":
                    change_behaviour_settings()  # config changes inside function so no return
                case "Reset Settings to Default":
                    config = {
                        "version": "1.21.11",
                        "mod_loader": "fabric",
                        "valid_versions": ["release"],
                        "mods_directory": "",
                        "auto_clear_jars": False,
                        "show_deatiled_logs": False,
                    }
                    # yes i did just copy and paste the entire default config
                case "Exit and Save":
                    save_config()
                    break

                case "Cancel":
                    break
        return

    main()
    return config  # so the app can use them immediately without reading the file again


def choose_mods() -> list[str]:
    """displays a questionary type ui to choose minecraft mods based off whats in mods.json, also where you configure settings

    Returns:
        list[str]: the initial modlist which stores the mods slug
        (needed for putting it through the modrinth api later in get_mods(),
        it is not the final list used in download_mods(),
    """
    global modpack_config
    initial_modlist: list[str] = []
    with open(mods_filepath) as file:
        json_modlist_data = json.load(file)

    category_map = {
        "Optimization & Performance": "optimization_mods",
        "PVP & Combat": "pvp_mods",
        "HUD & Info": "hud_mods",
        "QOL Mods": "qol_mods",
        "Visuals & Aesthetics": "visual_mods",
        "Audio & Ambience": "auditory_mods",
        "Building": "building_mods",
        "Miscellaneous": "misc_mods",
        "Multiplayer & Social\n": "social_mods",  # for that gap between categories and stuff
        "Finish & Download": "exit and save",
        "Configure Settings": "settings",
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
        elif json_key == "settings":
            modpack_config = configure_settings(modpack_config)
            continue
        elif json_key == "clear":
            initial_modlist = []
            continue
        elif json_key == "cancel":
            exit(0)

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
        # it only stores the value of the mod, and puts it in the initial modlist,
        # removes the name property and checked property

        initial_modlist = [
            mod
            for mod in initial_modlist
            if mod not in [mod["value"] for mod in mods_in_category]
        ]
        if selection is not None:
            initial_modlist += selection


def slug_to_id(target_slug: str) -> str:
    """converts the target slug into the id (id from modrinth)
    this is mainly for consistency purposes as slugs can change while ids cant
    if it wasnt obvious enough this is by using idslugmap.json

    Args:
        target_slug (str): target slug

    Returns:
        str: the id attached to the slug
    """
    id = next(
        (id for id, slug in id_to_slug_map.items() if slug == target_slug),
    )
    if id is None:
        print("yeah so the slug_to_id function mightve broken", style="error")
    return id


def get_mods(slugorid: str, api_session, is_dependency=False) -> list[dict[str, str]]:
    """gets the mods from initial modlist, puts them in modrinth api to get the mods download url and filename
    for the download section. also checks the mod for any required dependencies and downloads them recursively.
    dependencies installed have is_dependency set to True for obvious reasons. the mod and dependencies will later
    be returned in a nested list format (look at returns section)

    Args:
        slugorid (str): the slug/id of the mod, immediately turned into seperate slug and id variables
        where ids are used for the api requests and slugs for debugging and printing out console stuff

        is_dependency (bool, optional): if the mod is a dependency (installed because the other mods need it)
        we need it because dependencies are using ids for slugorid, and regular mods are using the slug,
        so we can make the id and slug different variables
        Defaults to False.

        api_session: just the api session being used, dont worry about it

    returns: list[dict[str, str]]: either an empty list (when the mod fails, so extend() doesnt crash), or an
    actual list of mod data. basically now the mod and its dependencies get added to a list in which it will later
    be appended to the real full_modlist list outside of the function
    """
    # initializing variables
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
    with threading_lock:
        if not id or id in visited_mod_ids:
            return []

        visited_mod_ids.add(id)
    # put id in instead for consistency, slugs can change while ids cant
    # api calling
    api_url = f"https://api.modrinth.com/v2/project/{id}/version"
    api_params = {
        "loaders": f'["{loaders.lower()}"]',
        "game_versions": f'["{version}"]',
        "include_changelog": "false",
    }
    response = api_session.get(api_url, params=api_params)
    data = response.json()
    if response.status_code != 200:
        print(
            f"Something wrong happened, status code: {response.status_code}",
            style="error",
        )
        failed_mods.append(slug)
        return []
    elif len(data) == 0:
        print(
            f"No files for fabric game version 1.21.11 found in mod {slug}",
            style="error",
        )
        failed_mods.append(slug)
        return []

    # filters data and versions

    latest_version = [  # filters out all versions not allowed in valid versions (usually alpha/beta versions)
        version for version in data if version.get("version_type") in valid_versions
    ]

    if not latest_version:
        print(
            f"Mod {slug} has no versions with {valid_versions} releases", style="error"
        )
        failed_mods.append(slug)
        return []
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
        return []

    # collected mods thingy
    collected_mods: list[dict[str, str]] = []
    mod_data = {
        "slug": slug,
        "filename": target_filename,
        "url": target_url,
    }
    collected_mods.append(mod_data)
    # it is a dependency, visual jukebox forgot to add the polymer in their dependencies
    if slug == "visual-jukebox":
        get_mods(slug_to_id("polymer"), api_session, is_dependency=True)

    # dependency search thingyu
    dependencies = [
        dependency
        for dependency in latest_version.get("dependencies", [])
        if dependency.get("dependency_type") == "required"
    ]
    for dependency in dependencies:
        try:
            dependency_mods_downloaded.append(slug)
            dependency_project_id: str = dependency.get("project_id")
            if dependency_project_id not in visited_mod_ids:
                new_dependency = get_mods(
                    dependency_project_id, api_session, is_dependency=True
                )
                collected_mods.extend(new_dependency)

        except Exception as error:
            print(
                f"\nHey, you should probably download this dependency yourself cuz the script couldnt do it: {repr(error)} ERROR",
                style="warning",
            )
            print(
                f"Link: https://modrinth.com/mod/{dependency_project_id}",
                style="warning",
            )
    return collected_mods


def clear_jar_files(directory_path: str) -> None:
    """clears .jar files in the mod directory where they download mods
    this is to prevent duplicates and weird glitches and stuff and outdated mods

    Args:
        directory_path (str): the directory path where the mods are installed
    """
    files = glob(os.path.join(directory_path, "*.jar"))
    for file in files:
        try:
            os.remove(file)
        except Exception as error:
            print(f"Could not remove {file}: {error}", style="error")


def download_mods(modlist: list[dict[str, str]], api_session) -> None:
    """downloads the mods in the modlist using the api, also has progress bars, top one is the main one
    where it tracks how many mods have been downloaded, and the other ones are sub-progress bars where it
    shows how much of the mods file contents have been downloaded
    Args:
        modlist (list[dict[str, str]]): the modlist in which the function uses to download the mods
        api_session: dont worry about it, its just the api session
    """

    def get_folder_path() -> str:
        """finds the folder path of the modpack by asking questions using questionary

        Returns:
            str: folder path
        """
        # finding the folder path (changes depending the mc launcher they use)
        # redefining appdata_filepath for this func only
        appdata_filepath = Path(
            os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")
        )
        folder_path_search_locations: dict[str, Path] = {
            "Minecraft Launcher": appdata_filepath / ".minecraft" / "modpacks",
            "Prism Launcher": appdata_filepath / "PrismLauncher" / "instances",
            "Lunar Client": Path.home() / ".lunarclient" / "offline" / "multiver",
            "Feather Client": appdata_filepath / ".feather" / "instances",
            "CurseForge": Path.home() / "curseforge" / "minecraft" / "instances",
        }
        launcher_choices: list[str] = [
            location
            for location, folderpath in folder_path_search_locations.items()
            if folderpath.exists()
        ]

        # if any of the filepaths in folder_path_search_locations doesnt exist
        if not launcher_choices:
            # not really a warning but i think yellow fits here so
            print(
                "Tip: You can copy and paste the path from the file explorer search bar",
                style="warning",
            )
            folder_path = questionary.path(
                "Could not find a modpacks folder location, please manually enter a path where mods will be downloaded:",
            ).ask()
            return folder_path

        # make them choose the launcher/path they want
        if len(launcher_choices) > 1:
            launcher_choice = questionary.select(
                "Which launcher do you want to use to download the mods?",
                choices=launcher_choices + ["\nCreate Manual Path"],
            ).ask()
        else:
            launcher_choice = launcher_choices[0]
        if launcher_choice == "Create Manual Path":
            print(
                "Tip: You can copy and paste the path from the file explorer search bar",
                style="warning",
            )
            folder_path = questionary.path(
                "Please enter a path where mods will be downloaded:",
            ).ask()
            return folder_path
        selected_path = folder_path_search_locations[launcher_choice]

        # checking if there are any modpack folders inside
        directories = [
            folder.name for folder in selected_path.iterdir() if folder.is_dir()
        ]
        # if there are
        if directories:
            modpack_choice = questionary.select(
                "Which modpack do you want your mods to be downloaded in?",
                choices=directories
                + [questionary.Separator(), "Create New Modpack Folder"],
            ).ask()
            if modpack_choice == "Create New Modpack Folder":
                modpack_name = questionary.text(
                    "What should the name of the new modpack be?"
                ).ask()
                return selected_path / modpack_name / "mods"
            return selected_path / modpack_choice / "mods"

        # if there werent, then create a new folder (name provided by user)
        modpack_name = questionary.text("What should the name of the new modpack be?")
        return selected_path / modpack_name / "mods"

    # getting folder path for downloading
    if modpack_config.get("mods_directory"):
        folder_path = modpack_config["mods_directory"]
    else:
        while True:
            folder_path = get_folder_path()
            confirm_folderpath = questionary.confirm(
                f"Is ({folder_path}) the correct filepath?"
            ).ask()
            if confirm_folderpath:
                os.makedirs(folder_path, exist_ok=True)
                break

    # clear files first before downloading or not
    if modpack_config.get("auto_clear_jars"):
        clear_jar_files(folder_path)
    else:
        clear_folder = questionary.confirm(
            "Should we delete all .jar files in the minecraft mods folder path to remove duplicates? (RECOMMENDED)"
        ).ask()
        if clear_folder:
            clear_jar_files(folder_path)
            print("Everything cleared.", style="success")

    # actually downloading mods (with progress bar)
    main_progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
    )
    mods_downloaded = main_progress.add_task("Downloading Mods...", total=len(modlist))
    mod_download_progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        DownloadColumn(),
    )
    progress_group = Group(main_progress, mod_download_progress)
    with Live(progress_group, refresh_per_second=10):

        def download_one_mod(target_mod):
            """just so the threadpoolexecutor works well so the async nature works
            basically it takes one mod from the full_modlist and downloads it"""
            download_path = os.path.join(folder_path, target_mod.get("filename"))
            url = target_mod.get("url")
            if not url:
                print(f"{target_mod} has no url!")
                return

            response = api_session.get(url, stream=True)
            response.raise_for_status()

            mod_filesize = int(response.headers.get("Content-Length", 0))
            mod_downloading_progress_id = mod_download_progress.add_task(
                f"downloading {target_mod.get('slug')}",
                total=mod_filesize,
            )
            with open(download_path, "wb") as file:
                for chunk in response.iter_content(
                    chunk_size=8192
                ):  # idk what tf this does but it works according to google so
                    file.write(chunk)
                    mod_download_progress.update(
                        mod_downloading_progress_id, advance=8192
                    )

            main_progress.update(mods_downloaded, advance=1)
            mod_download_progress.remove_task(mod_downloading_progress_id)

        with ThreadPoolExecutor(max_workers=5) as executor:
            executor.map(download_one_mod, modlist)


if __name__ == "__main__":
    # program initialization (.json files, declaring global variables, etc)
    builder.main()
    with open(config_filepath) as file:
        modpack_config: dict[str, Any] = json.load(file)
    with open(idslugmap_filepath) as file:
        id_to_slug_map: dict[str, str] = json.load(file)
    # now the program starts
    initial_modlist = choose_mods()
    with requests.Session() as api_session:
        with ThreadPoolExecutor() as executor:
            results = executor.map(
                lambda mod: get_mods(mod, api_session), initial_modlist
            )
            for mod_data in results:
                if mod_data is not None:
                    full_modlist.extend(mod_data)
        # for mod in initial_modlist:
        #     get_mods(mod, api_session)  # automatically appends to full_modlist
        download_mods(full_modlist, api_session)
        print(
            f"\n[green]{len(full_modlist)} mods downloaded![/green] ({len(dependency_mods_downloaded)} of which were dependencies)"
        )
        if len(failed_mods) > 0:
            print(
                f"{len(failed_mods)} mods failed to download: {failed_mods}",
                style="error",
            )
        input("Press Enter to exit.")

# - more mods (if mods are too much ill figure out a way to better find mods and stuff)
# - better progress bars
# - better error handling
# - code polish
