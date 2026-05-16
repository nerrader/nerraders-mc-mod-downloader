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
    """Displays a questionary UI to choose mods and configure settings.

    Args:
        current_config (config.Config): The config, which could be changed in the configure_settings().
        json_modlist_data (dict[str, list]): The mods.json loaded from the builder.py.
    Returns:
        tuple: to wrap both of them into a sort of list

        list[str]: the initial modlist which stores the mods slug
        (needed for putting it through the modrinth api later in get_mods(),
        it is not the final list used in download_mods(),

        config.Config: the modpack_config
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
    """Converts the target mod slug to the corresponding mod ID.
    This function is usually used to retain consistency as mod slugs can change, while IDs cannot.

    Returns:
        str: The ID of the slug.
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


def _fetch_mod_data(
    mod_id,
    download_context: DownloadContext,
    api_session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    mod_loader: str = download_context.modpack_config.mod_loader
    version: str = download_context.modpack_config.version

    api_url = f"https://api.modrinth.com/v2/project/{mod_id}/version"
    api_params = {
        "loaders": f'["{mod_loader.lower()}"]',
        "game_versions": f'["{version}"]',
        "include_changelog": "false",
    }
    api_headers = {"User-Agent": const.USER_AGENT}
    session = api_session or requests
    response: requests.Response = session.get(
        api_url, params=api_params, headers=api_headers, timeout=const.API_TIMEOUT
    )
    response.raise_for_status()
    data = response.json()
    if len(data) == 0:
        raise ValueError(f"No files available for {version}")
    return data


def _find_latest_mod_version(
    mod_api_data: list[dict[str, Any]], valid_version_types: list[str]
):
    valid_mod_versions = [
        version
        for version in mod_api_data
        if version.get("version_type") in valid_version_types
    ]

    if not valid_mod_versions:
        raise ValueError(f"Mod does not have any {valid_version_types} releases.")
    return valid_mod_versions[0]


def _find_latest_mod_file_data(latest_version: dict[str, Any]) -> tuple[str, str]:
    if not (files := latest_version.get("files")):
        raise ValueError("Target mod version contains no files.")

    target_file = next(  # look at files, find the latest one that is a primary file
        (file for file in files if file.get("primary")),
        files[0],
    )

    if not (target_filename := target_file["filename"]) or not (
        target_url := target_file["url"]
    ):
        raise ValueError("Target mod has no filename or download URL")
    return (target_filename, target_url)


def _resolve_dependencies(
    latest_version: dict[str, Any],
    api_session: requests.Session,
    download_context: DownloadContext,
) -> list[dict[str, str]]:
    """Parses required dependencies and recursively fetches their download data."""
    resolved_dependencies: list[dict[str, str]] = []

    dependencies = [
        dep
        for dep in latest_version.get("dependencies", [])
        if dep.get("dependency_type") == "required"
    ]

    for dependency in dependencies:
        if not (dependency_project_id := dependency.get("project_id")):
            continue
        # Threading lock check is handled safely inside the next get_mods recursive call
        try:
            new_dependencies = get_mods(
                dependency_project_id,
                api_session,
                download_context,
            )
            if new_dependencies:
                resolved_dependencies.extend(new_dependencies)
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

    return resolved_dependencies


def get_mods(
    mod_id: str,
    api_session: requests.Session,
    download_context: DownloadContext,
) -> list[dict[str, str]] | list:
    """Recursively fetches download metadata for a mod (mod_id) and its required dependencies.

    returns: list[dict[str, str]]: A list of dictionaries, each containing 'slug', 'filename', and 'url'
        attributes for the target mod and any found dependencies.
        Returns an empty list if data resolution or network requests fail. (so .extend() doesn't crash)
    """
    # initializing variables

    mod_slug = download_context.id_slug_map[mod_id]

    # to prevent race conditions, we need a threading lock
    with const.THREADING_LOCK:
        if not mod_id or mod_id in download_context.visited_mod_ids:
            return []

        download_context.visited_mod_ids.add(mod_id)

    # put id in instead for consistency, slugs can change while ids cant
    try:
        data = _fetch_mod_data(mod_id, download_context, api_session)
        latest_version = _find_latest_mod_version(
            data, download_context.modpack_config.valid_versions
        )
        target_filename, target_url = _find_latest_mod_file_data(latest_version)
    except requests.HTTPError as error:
        response_code = (
            error.response.status_code if error.response is not None else "Unknown"
        )
        download_context.failed_mods.append(
            {"slug": mod_slug, "cause": f"API HTTP Error Status: {response_code}"}
        )
        return []
    except ValueError as error:
        download_context.failed_mods.append({"slug": mod_slug, "cause": str(error)})
        return []

    collected_mods: list[dict[str, str]] = []
    mod_data = {
        "slug": mod_slug,
        "filename": target_filename,
        "url": target_url,
    }
    collected_mods.append(mod_data)

    # dependency search thingy
    resolved_dependencies = _resolve_dependencies(
        latest_version, api_session, download_context
    )
    collected_mods.extend(resolved_dependencies)
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
    """NOTE: This function is a helper function for get_download_folder_path()

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

    This function can also exit out of the program if the user cancels the manual filepath prompt,
    as the program cannot function if there is no path given to download the mods.
    """
    # not really a warning but i think yellow fits here so
    print(
        "Tip: You can copy and paste the path from the file explorer search bar",
        style="warning",
    )
    while True:
        folder_path_str: str = questionary.path(
            prompt,
            style=const.QUESTIONARY_STYLE,
        ).ask()
        if folder_path_str is None or folder_path_str.lower() in ("exit", "quit", "q"):
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
    """
    Downloads mods in the modlist by fetching data from the mod's link. Also has progress bars.
    """

    # clear files first before downloading or not
    modpack_folderpath: Path = get_download_folder_path(download_context)
    modpack_folderpath.mkdir(parents=True, exist_ok=True)
    should_clear_folders: bool = (
        download_context.modpack_config.behaviour_settings.auto_clear_jars
    )
    clear_folder = (
        questionary.confirm(
            "Delete all .jar files in the minecraft mods folder path to remove duplicates?"
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
            if not (url := target_mod.get("url")):
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
                lambda mod: get_mods(
                    slug_to_id(mod, id_slug_map), api_session, download_context
                ),
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
