from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from sys import exit
from typing import Any

import questionary
import requests
from rich.console import Group
from rich.live import Live
from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    DownloadColumn,
    TaskProgressColumn,
    MofNCompleteColumn,
)
from rich.table import Table

# builder for tool initialization, creating required appdata folders and stuff like that
from mc_mods_downloader import builder, constants as const, config

# overriding default print with rich print
print = const.CONSOLE.print


@dataclass
class DownloadContext:
    modpack_config: config.Config
    id_slug_map: dict[str, str]
    visited_mod_ids: set[str] = field(default_factory=set, repr=False)
    full_modlist: list[dict[str, str]] = field(default_factory=list)
    failed_mods: list[dict[str, str]] = field(default_factory=list)
    dependency_mods_counter: int = field(default=0)


def _get_mod_choices(
    initial_modlist: list[str],
    current_loader: str,
    mods_in_category: list[dict[str, Any]],
) -> list[questionary.Choice]:
    """
    NOTE: This function is a helper function for main_menu()

    This gets the appropriate mod choices for the checkbox selection prompt according
    to the current loader.

    Args:
        initial_modlist (list[str]): The initial modlist.
        current_loader (str): The current mod loader the user is using, used to filter out
        mods that are incompatible with the loader.
        mods_in_category (list[dict[str, Any]]): The mods that are appropriate to the user's
        choosing category.

    Returns:
        list[questionary.Choice]: The list of mods that are able to be chosen.
    """
    return [
        questionary.Choice(
            title=mod["name"],
            value=mod["value"],
            checked=mod["value"] in initial_modlist,
            disabled=None
            if current_loader.lower() in mod["loaders"]
            else f"Requires {mod['loaders']}",
        )
        for mod in mods_in_category
    ]


def _handle_category_selection(
    category_name: str,
    mods_in_category: list[dict[str, str]],
    current_config: config.Config,
    initial_modlist: list[str],
) -> list[str]:
    mod_choices = _get_mod_choices(
        initial_modlist, current_config.mod_loader, mods_in_category
    )

    selection = questionary.checkbox(
        message=f"Choose mods from {category_name}",
        choices=mod_choices,
        style=const.QUESTIONARY_STYLE,
    ).ask()

    # for every mod in everything the user has selected so far,
    # remove every mod that is in the category that the user is in
    modvalues_in_category: set[str] = {mod["value"] for mod in mods_in_category}
    initial_modlist = [
        mod for mod in initial_modlist if mod not in modvalues_in_category
    ]
    # then readd it back using this
    # this is to avoid duplicates and allow for deletion
    initial_modlist.extend(selection or [])

    return initial_modlist


def main_menu(
    current_config: config.Config, json_modlist_data: dict[str, list]
) -> tuple[list[str], config.Config]:
    """displays a questionary type ui to choose minecraft mods based off whats in mods.json, also where you configure settings

    Args:
        current_config (config.Config): The config, which could be changed in the configure_settings().
        json_modlist_data (dict[str, list]): The mods.json loaded from the builder.py.
    Returns:
        tuple: to wrap both of them into a sort of list

        list[str]: the initial modlist which stores the mods slug
        (needed for putting it through the modrinth api later in get_mods(),
        it is not the final list used in download_mods(),

        config.Config: the modpack_config (if they used configure_settings)
    """
    initial_modlist: list[str] = []

    category_map: dict[str, str] = {
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
        category_choice: str = questionary.select(
            "Choose a category to browse mods",
            choices=list(category_map.keys()),
            style=const.QUESTIONARY_STYLE,
        ).ask()
        category_map_value = category_map[category_choice]

        match category_map_value:
            case "exit and save":
                return (initial_modlist, current_config)
            case "settings":
                # new config basically
                current_config = config.main_settings_loop(current_config)
                continue
            case "clear":
                initial_modlist = []
                continue
            case "cancel":
                exit(0)

        mods_in_category: list[dict[str, str]] = json_modlist_data[category_map_value]

        initial_modlist = _handle_category_selection(
            category_choice,
            mods_in_category,
            current_config,
            initial_modlist,
        )


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
    mod_loader: str = download_context.modpack_config.mod_loader
    version: str = download_context.modpack_config.version
    valid_versions: list[str] = download_context.modpack_config.valid_versions
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
        "loaders": f'["{mod_loader.lower()}"]',
        "game_versions": f'["{version}"]',
        "include_changelog": "false",
    }
    api_headers = {"User-Agent": const.USER_AGENT}
    response = api_session.get(
        api_url, params=api_params, headers=api_headers, timeout=const.API_TIMEOUT
    )
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

    # dependency search thingy
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


def clear_jar_files(directory_path: Path) -> None:
    """clears .jar files in the mod directory where they download mods
    this is to prevent duplicates and weird glitches and stuff and outdated mods

    Args:
        directory_path (str | Path): the directory path where the mods are installed
    """
    files = directory_path.glob("*.jar")
    for file in files:
        try:
            file.unlink()
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
    if const.USER_OS == "win32":
        folderpath_search_locations = {
            "Minecraft Launcher": const.APPDATA_FILEPATH / ".minecraft" / "modpacks",
            "Prism Launcher": const.APPDATA_FILEPATH / "PrismLauncher" / "instances",
            "Lunar Client": const.HOME_FILEPATH
            / ".lunarclient"
            / "offline"
            / "multiver",
            "Feather Client": const.APPDATA_FILEPATH / ".feather" / "instances",
            "CurseForge": const.HOME_FILEPATH
            / "curseforge"
            / "minecraft"
            / "instances",
        }
    else:  # sorry but for linux or macos or anything else its not worth the unreliability of the filepaths
        return (
            enter_manual_path(
                "Automatic launcher detection is only available on Windows. Please enter the path to your mods folder manually: "
            ),
            True,
        )
    launcher_choices: list[str] = [
        location
        for location, folderpath in folderpath_search_locations.items()
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

    launcher_path = folderpath_search_locations[launcher_choice]
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
            "What should the name of the new modpack be?",
            style=const.QUESTIONARY_STYLE,
        ).ask()
        return launcher_path / modpack_name / "mods"

    modpack_choice = questionary.select(
        "Which modpack do you want your mods to be downloaded in?",
        choices=directories + [questionary.Separator(), "Create New Modpack Folder"],
        style=const.QUESTIONARY_STYLE,
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
    if download_context.modpack_config.mods_directory is not None:  # if not empty
        return download_context.modpack_config.mods_directory

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

    This funciton can also exit out of the program if the user cancels the manual filepath prompt,
    as the program cannot function if there is no path given to download the mods.
    """
    # not really a warning but i think yellow fits here so
    print(
        "Tip: You can copy and paste the path from the file explorer search bar",
        style="warning",
    )
    while True:
        folder_path_str: str = questionary.path(
            prompt, style=const.QUESTIONARY_STYLE
        ).ask()
        if folder_path_str is None or folder_path_str.lower() in ["exit", "quit", "q"]:
            exit("Error: No folder path provided.")

        folder_path = Path(folder_path_str)

        if folder_path.exists() and folder_path.is_dir():
            return folder_path

        print(
            "Folder path does not exist or is not a directory. Try again", style="error"
        )


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
    modpack_folderpath.mkdir(parents=True, exist_ok=True)
    should_clear_folders: bool = (
        download_context.modpack_config.behaviour_settings.auto_clear_jars
    )
    clear_folder = (
        questionary.confirm(
            "Should we delete all .jar files in the minecraft mods folder path to remove duplicates?"
        )
        .skip_if(should_clear_folders, default=True)
        .ask()
    )
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
            download_path = modpack_folderpath / target_mod.get("filename")
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

            # idk what tf this does but it works according to google so
            with open(download_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=const.CHUNK_SIZE):
                    file.write(chunk)
                    mod_download_progress.update(
                        mod_downloading_progress_id, advance=len(chunk)
                    )
            # updating the progress bars and removing the mod progress bar (mod finished downloading)
            main_progress.update(mods_downloaded, advance=1)
            mod_download_progress.remove_task(mod_downloading_progress_id)

        with ThreadPoolExecutor() as executor:
            executor.map(download_one_mod, modlist)


def get_download_summary(download_context: DownloadContext) -> None:
    """This shows the download summary which includes:
    - The amount of mods downloaded
    - The amount of depedency mods downloaded
    - The mods that failed to download and the cause, formatted in a table
    """
    print(
        f"\n[green]{len(download_context.full_modlist)} mods downloaded![/green] ({download_context.dependency_mods_counter} of which were dependencies)"
    )

    # if there were any failed mods, add them to a table
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
    initial_modlist, new_modpack_config = main_menu(modpack_config, mods_json)
    download_context = DownloadContext(new_modpack_config, id_slug_map)

    # session so the tcp connection doesnt reset
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
