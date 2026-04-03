import requests
from glob import glob
import os
from sys import exit
import questionary
from rich.console import Group
from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    DownloadColumn,
    TaskProgressColumn,
    MofNCompleteColumn,
)
from rich.live import Live
from rich.table import Table
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

# project initialization module (my own one)
from mc_mods_downloader import builder

# global variables initialization, global variables (constants) have to start with const.
from mc_mods_downloader import constants as const

# overriding default print with rich print
print = const.CONSOLE.print


@dataclass
class DownloadContext:
    modpack_config: dict[str, Any]
    id_slug_map: dict[str, str]
    visited_mod_ids: set[str] = field(default_factory=set, repr=False)
    full_modlist: list[dict[str, str]] = field(default_factory=list)
    failed_mods: list[dict[str, str]] = field(default_factory=list)
    dependency_mods_counter: int = field(default=0)


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
        data = requests.get(
            api_url, timeout=const.API_TIMEOUT, headers={"User-Agent": const.USER_AGENT}
        ).json()  # pretty much guaranteed to be 200
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

    def change_behaviour_settings() -> dict[str, bool]:
        """behaviour settings are basically just the true/false value settings
        returns None as the changes happen inside this function directly
        """
        # gets the current behaviour settings
        new_behaviour_settings: dict[str, bool] = config["behaviour_settings"]
        while True:
            behaviour_settings_chioces = (
                questionary.Choice(
                    title=f"Skip .jar files Deletion Confirmation [{new_behaviour_settings['auto_clear_jars']}]",
                    value="auto_clear_jars",
                ),
                questionary.Choice(
                    title=f"Show Detailed Logs [{new_behaviour_settings['show_detailed_logs']}]",
                    value="show_detailed_logs",
                ),
                questionary.Choice(title="Go Back", value="back"),
            )

            selection = questionary.select(
                "Behaviour Settings",
                choices=behaviour_settings_chioces,
                default=None,
            ).ask()
            if selection == "back" or selection is None:
                return new_behaviour_settings
            else:
                new_behaviour_settings[selection] = not new_behaviour_settings[
                    selection
                ]

    def main_settings_loop() -> None:
        """the main menu, where the user selects a thing to change"""
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
                    questionary.Separator(),
                    "Exit and Save",
                    "Reset Settings to Default",
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
                    config["behaviour_settings"] = change_behaviour_settings()
                case "Reset Settings to Default":
                    config = builder.get_default_config()
                case "Exit and Save":
                    builder.save_config(config)
                    break

                case "Cancel":
                    break
        return

    main_settings_loop()
    return config


def main_menu(current_config, json_modlist_data) -> tuple[list[str], dict]:
    """displays a questionary type ui to choose minecraft mods based off whats in mods.json, also where you configure settings

    Returns:
        tuple: to wrap both of them into a sort of list

        list[str]: the initial modlist which stores the mods slug
        (needed for putting it through the modrinth api later in get_mods(),
        it is not the final list used in download_mods(),

        dict: the modpack_config (if they used configure_settings)

    """
    initial_modlist: list[str] = []
    updated_config: dict = {}

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

        match json_key:
            case "exit and save":
                return (initial_modlist, updated_config)
            case "settings":
                updated_config = configure_settings(current_config)
                continue
            case "clear":
                initial_modlist = []
                continue
            case "cancel":  # cancel
                exit(0)

        mods_in_category: list[dict[str, str]] = json_modlist_data.get(json_key, [])
        modvalues_in_category: set[str] = {mod["value"] for mod in mods_in_category}

        mod_choices = [
            {
                "name": mod["name"],
                "value": mod["value"],
                "checked": mod["value"] in initial_modlist,
            }
            for mod in mods_in_category
        ]

        selection = questionary.checkbox(
            message=f"Choose mods from {category_choice}", choices=mod_choices
        ).ask()

        # for every mod in everything the user has selected so far,
        # remove every mod that is in the category that the user is in
        initial_modlist = [
            mod for mod in initial_modlist if mod not in modvalues_in_category
        ]
        # then readd it back using this
        # this is to avoid duplicates and allow for deletion
        if selection is not None:
            initial_modlist += selection


def slug_to_id(target_slug: str, id_slug_map: dict[str, str]) -> str:
    """converts the target slug into the id (id from modrinth)
    this is mainly for consistency purposes as slugs can change while ids cant
    if it wasnt obvious enough this is done by using idslugmap.json

    Args:
        target_slug (str): target slug

    Returns:
        str: the id attached to the slug
    """
    id = next(
        (id for id, slug in id_slug_map.items() if slug == target_slug),
    )
    if id is None:
        print(
            "yeah so the slug_to_id function mightve broken or there was no id",
            style="error",
        )
    return id


def get_mods(
    slugorid: str,
    api_session: requests.Session,
    download_context: DownloadContext,
    is_dependency=False,
) -> list[dict[str, str]]:
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
    loaders = download_context.modpack_config["mod_loader"]
    version = download_context.modpack_config["version"]
    valid_versions = download_context.modpack_config.get("valid_versions", "release")
    # for dependencies the "slug" is an id
    if is_dependency:
        id = slugorid
        slug = download_context.id_slug_map[id]
    # turn everything into an id for consistency
    else:
        id = slug_to_id(slugorid, download_context.id_slug_map)
        slug = slugorid
    # so we dont have to do an api call if weve done the mod before
    with const.THREADING_LOCK:
        if not id or id in download_context.visited_mod_ids:
            return []

        download_context.visited_mod_ids.add(id)
    # put id in instead for consistency, slugs can change while ids cant
    # api calling
    api_url = f"https://api.modrinth.com/v2/project/{id}/version"
    api_params = {
        "loaders": f'["{loaders.lower()}"]',
        "game_versions": f'["{version}"]',
        "include_changelog": "false",
    }
    response = api_session.get(api_url, params=api_params, timeout=const.API_TIMEOUT)
    data = response.json()
    if response.status_code != 200:
        download_context.failed_mods.append(
            {"slug": slug, "cause": f"status code {response.status_code}"}
        )
        return []
    elif len(data) == 0:
        download_context.failed_mods.append(
            {"slug": slug, "cause": f"no files for version {version}"}
        )
        return []

    # filters data and versions

    latest_version = [  # filters out all versions not allowed in valid versions (usually alpha/beta versions)
        version for version in data if version.get("version_type") in valid_versions
    ]

    if not latest_version:
        download_context.failed_mods.append(
            {"slug": slug, "cause": f"mod doesnt have any {valid_versions} releases"}
        )
        return []
    latest_version = latest_version[0]  # the actual latest version

    target_file = next(  # look at files, find the latest one that is a primary file
        (file for file in latest_version.get("files", []) if file.get("primary")),
        latest_version["files"][0],
    )
    target_filename = target_file["filename"]
    target_url = target_file["url"]

    if not target_filename or not target_url:
        download_context.failed_mods.append(
            {"slug": slug, "cause": "the url and filename doesnt exist for some reason"}
        )
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
        polymer_mod_data = get_mods(
            slug_to_id("polymer", download_context.id_slug_map),
            api_session,
            download_context,
            is_dependency=True,
        )
        collected_mods.extend(polymer_mod_data)

    # dependency search thingyu
    dependencies = [
        dependency
        for dependency in latest_version.get("dependencies", [])
        if dependency.get("dependency_type") == "required"
    ]
    for dependency in dependencies:
        try:
            dependency_project_id: str = dependency.get("project_id")
            if dependency_project_id not in download_context.visited_mod_ids:
                new_dependency = get_mods(
                    dependency_project_id,
                    api_session,
                    download_context,
                    is_dependency=True,
                )
                collected_mods.extend(new_dependency)
                download_context.dependency_mods_counter += 1

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


def clear_jar_files(directory_path: str | Path) -> None:
    """clears .jar files in the mod directory where they download mods
    this is to prevent duplicates and weird glitches and stuff and outdated mods

    Args:
        directory_path (str | Path): the directory path where the mods are installed
    """
    files = glob(os.path.join(directory_path, "*.jar"))
    for file in files:
        try:
            os.remove(file)
        except Exception as error:
            print(f"Could not remove {file}: {error}", style="error")


def _get_selected_launcher_path() -> tuple[Path, bool]:
    """WARNING: THIS FUNCITON IS ONLY MEANT TO BE USED IN get_download_folder_path()!!!!!

    basically this function sees which launcher the user has, makes the user select one
    (unless only one potential launcher path is found)

    then based off the folder_path_search locations dict, find the folder path for the launcher
    the user selected, and return it.
    Returns: (things wrapped in the tuple)
        Path: The launcher path selected by the user
        bool: Whether the user created a manual path
    """
    # redefining APPDATA_FILEPATH for this func only
    APPDATA_FILEPATH = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    folder_path_search_locations: dict[str, Path] = {
        "Minecraft Launcher": APPDATA_FILEPATH / ".minecraft" / "modpacks",
        "Prism Launcher": APPDATA_FILEPATH / "PrismLauncher" / "instances",
        "Lunar Client": Path.home() / ".lunarclient" / "offline" / "multiver",
        "Feather Client": APPDATA_FILEPATH / ".feather" / "instances",
        "CurseForge": Path.home() / "curseforge" / "minecraft" / "instances",
    }
    launcher_choices: list[str] = [
        location
        for location, folderpath in folder_path_search_locations.items()
        if folderpath.exists()
    ]

    # if any of the filepaths in folder_path_search_locations doesnt exist
    if not launcher_choices:
        return (
            enter_manual_path(
                "Could not find a modpacks folder location, please manually enter a path where mods will be downloaded:"
            ),
            True,
        )

    # make them choose the launcher/path they want
    if len(launcher_choices) > 1:
        launcher_choice = questionary.select(
            "Which launcher do you want to use to download the mods?",
            choices=launcher_choices + [questionary.Separator(), "Create Manual Path"],
        ).ask()
        if launcher_choice == "Create Manual Path":
            return (
                enter_manual_path("Please enter a path where mods will be downloaded:"),
                True,
            )
    else:
        launcher_choice = launcher_choices[0]

    launcher_path = folder_path_search_locations[launcher_choice]
    return (launcher_path, False)


def _get_modpack_folder(launcher_path: Path) -> Path:
    """WARNING: THIS FUNCITON IS ONLY MEANT TO BE USED IN get_download_folder_path()!!!!!

    Args:
        launcher_path (Path): launcher path given by the other helper function, _get_selected_launcher_path()

    Returns:
        Path: the selected modpack folderpath
    """
    directories = [folder.name for folder in launcher_path.iterdir() if folder.is_dir()]

    if not directories:
        modpack_name = questionary.text(
            "What should the name of the new modpack be?"
        ).ask()
        return launcher_path / modpack_name / "mods"

    modpack_choice = questionary.select(
        "Which modpack do you want your mods to be downloaded in?",
        choices=directories + [questionary.Separator(), "Create New Modpack Folder"],
    ).ask()
    if modpack_choice != "Create New Modpack Folder":
        return launcher_path / modpack_choice / "mods"
    modpack_name = questionary.text("What should the name of the new modpack be?").ask()
    return launcher_path / modpack_name / "mods"


def get_download_folder_path(download_context: DownloadContext) -> Path:
    """finds the folder path of the modpack by using two other helper functions,
    _get_selected_launcher_path() and _get_modpack_folder(),
    if user has default path in config.json, it uses that instead and skips the prompts

    also asks the user a confirm prompt to confirm the folder path they selected, if so, return folder path
    Returns:
        str: folder path
    """
    # checks if they already have a default path in their settings/config.json
    if download_context.modpack_config.get("mods_directory"):  # if not empty
        return download_context.modpack_config["mods_directory"]

    while True:
        launcher_path, is_manual_path = _get_selected_launcher_path()
        if is_manual_path:
            modpack_folderpath = launcher_path
        else:
            modpack_folderpath = _get_modpack_folder(launcher_path)
        # getting folder path for downloading
        if not modpack_folderpath:
            print(
                "Folder path was empty so we are sending you right back to the selection prompts",
                style="error",
            )
            continue
        confirm_folderpath = questionary.confirm(
            f"Is ({modpack_folderpath}) the correct filepath?"
        ).ask()
        if confirm_folderpath:
            break
    return modpack_folderpath

    # checking if there are any modpack folders inside


def enter_manual_path(prompt: str) -> Path:
    """this function forces the user to enter a manual path, this is usually only used in
    get_download_folder_path()

    Args:
        prompt (str): the prompt the user gets when asked to enter a path via questionary.path manually

    Returns:
        Path: The path object returned by this function
    """
    # not really a warning but i think yellow fits here so
    print(
        "Tip: You can copy and paste the path from the file explorer search bar",
        style="warning",
    )
    folder_path = questionary.path(
        prompt,
    ).ask()
    return Path(folder_path)


def download_mods(
    modlist: list[dict[str, str]],
    api_session: requests.Session,
    download_context: DownloadContext,
) -> None:
    """downloads the mods in the modlist using the api, also has progress bars, top one is the main one
    where it tracks how many mods have been downloaded, and the other ones are sub-progress bars where it
    shows how much of the mods file contents have been downloaded
    Args:
        modlist (list[dict[str, str]]): the modlist in which the function uses to download the mods
        api_session: dont worry about it, its just the api session
    """

    # clear files first before downloading or not
    modpack_folderpath = get_download_folder_path(download_context)
    os.makedirs(modpack_folderpath, exist_ok=True)
    should_clear_folders: bool = download_context.modpack_config[
        "behaviour_settings"
    ].get("auto_clear_jars")
    if should_clear_folders:
        clear_jar_files(modpack_folderpath)
    else:
        clear_folder = questionary.confirm(
            "Should we delete all .jar files in the minecraft mods folder path to remove duplicates? (RECOMMENDED)"
        ).ask()
        if clear_folder:
            clear_jar_files(modpack_folderpath)
            print("Everything cleared.", style="success")

    # actually downloading mods (with progress bar)

    # the making of the progress bar (this is for mods_downloaded/total mods)
    main_progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
    )

    # the mods itself
    mods_downloaded = main_progress.add_task("Downloading Mods...", total=len(modlist))
    mod_download_progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        DownloadColumn(),
    )
    progress_group = Group(main_progress, mod_download_progress)
    with Live(progress_group, refresh_per_second=10):

        def download_one_mod(target_mod) -> None:
            """just so the threadpoolexecutor works well so the async nature works
            basically it takes one mod from the full_modlist and downloads it"""
            download_path = os.path.join(modpack_folderpath, target_mod.get("filename"))
            url = target_mod.get("url")
            if not url:
                print(f"{target_mod} has no url!")
                return

            response = api_session.get(url, stream=True, timeout=const.API_TIMEOUT)
            response.raise_for_status()

            mod_filesize = int(response.headers.get("Content-Length", 0))
            mod_downloading_progress_id = mod_download_progress.add_task(
                f"downloading {target_mod.get('slug')}",
                total=mod_filesize,
            )
            with open(download_path, "wb") as file:
                for chunk in response.iter_content(
                    chunk_size=const.CHUNK_SIZE
                ):  # idk what tf this does but it works according to google so
                    file.write(chunk)
                    mod_download_progress.update(
                        mod_downloading_progress_id, advance=len(chunk)
                    )
            # updating the progress bars and removing the mod progress bar (mod finished downloading)
            main_progress.update(mods_downloaded, advance=1)
            mod_download_progress.remove_task(mod_downloading_progress_id)

        with ThreadPoolExecutor(max_workers=5) as executor:
            executor.map(download_one_mod, modlist)


def get_download_summary(download_context: DownloadContext) -> None:
    print(
        f"\n[green]{len(download_context.full_modlist)} mods downloaded![/green] ({download_context.dependency_mods_counter} of which were dependencies)"
    )
    if len(download_context.failed_mods) > 0:
        failed_mods_table = Table(
            title="Failed Mods", show_header=True, header_style="bold red"
        )
        failed_mods_table.add_column("Mod Slug")
        failed_mods_table.add_column("Cause of Failure", style="red")

        for mod in download_context.failed_mods:
            failed_mods_table.add_row(
                mod.get("slug", "Unknown"), mod.get("cause", "Unknown")
            )
        print("")
        print(failed_mods_table)  # newlines to make it look better overall
        print("")


def main() -> None:
    # getting the json files
    mods_json, id_slug_map, modpack_config = builder.main()
    # now the program starts
    initial_modlist, config_update = main_menu(modpack_config, mods_json)
    modpack_config.update(config_update)
    # session so the tcp connection doesnt reset
    download_context = DownloadContext(modpack_config, id_slug_map)
    with requests.Session() as api_session:
        api_session.headers.update({"User-Agent": const.USER_AGENT})
        # threadpoolexecutor to allow multiple thread execution (async pretty much)
        with ThreadPoolExecutor() as executor:
            results = executor.map(
                lambda mod: get_mods(mod, api_session, download_context),
                initial_modlist,
            )
            for mod_data in results:
                if mod_data is not None:
                    download_context.full_modlist.extend(mod_data)
        download_mods(download_context.full_modlist, api_session, download_context)
        get_download_summary(download_context)
        input("Press Enter to Exit")


if __name__ == "__main__":
    main()


# for v4.0.0
# - make everything async, use asyncio, and replace threadpoolexecutor with that
# - more mods (if mods are too much ill figure out a way to better find mods and stuff)
# - refactor main() maybe, get_mods(), and main_menu()
# - make the detailed_logs config actually work
