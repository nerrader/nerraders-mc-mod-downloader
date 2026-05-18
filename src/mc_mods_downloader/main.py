from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from sys import exit as sysexit
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

from mc_mods_downloader import builder, config, constants as const
from mc_mods_downloader.utils.prompt_user_for_directory import prompt_user_for_directory

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


def main_menu(
    current_config: config.Config, json_modlist_data: dict[str, list]
) -> tuple[list[str], config.Config]:
    """Displays a questionary UI to choose mods and configure settings.

    Args:
        current_config (config.Config): The config, which could be changed in the configure_settings().
        json_modlist_data (dict[str, list]): The mods.json loaded from the builder.py.
    Returns:
        tuple[list[str], config.Config]:
            - list[str]: The initial modlist used to store the slug of mods.
            - config.Config: The new modpack config.
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
                sysexit(0)

        mods_in_category: list[dict[str, str]] = json_modlist_data[category_map_value]

        mod_choices = [
            questionary.Choice(
                title=mod["name"],
                value=mod["value"],
                checked=mod["value"] in initial_modlist,
                disabled=None
                if current_config.mod_loader.lower() in mod["loaders"]
                else f"Requires {mod['loaders']}",
            )
            for mod in mods_in_category
        ]

        selection = questionary.checkbox(
            message=f"Choose mods from {category_choice}",
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


def slug_to_id(target_slug: str, id_slug_map: dict[str, str]) -> str:
    """Converts the target mod slug to the corresponding mod ID.
    This function is usually used to retain consistency as mod slugs can change, while IDs cannot.

    Returns:
        str: The ID of the slug.
    """
    id = next((id for id, slug in id_slug_map.items() if slug == target_slug), None)
    if id is None:
        raise ValueError(f"Could not find a mod ID for the slug: {target_slug}")
    return id


def resolve_dependencies(
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
) -> list[dict[str, str]]:
    """Uses the mod_id to fetch all the mod metadata required uisng the Modrinth API
    for the downloading of the mod later on.
    """

    mod_slug = download_context.id_slug_map[mod_id]
    with const.THREADING_LOCK:
        if not mod_id or mod_id in download_context.visited_mod_ids:
            return []
        download_context.visited_mod_ids.add(mod_id)

    try:
        mod_loader = download_context.modpack_config.mod_loader
        version = download_context.modpack_config.version

        api_url = f"https://api.modrinth.com/v2/project/{mod_id}/version"
        api_params = {
            "loaders": f'["{mod_loader.lower()}"]',
            "game_versions": f'["{version}"]',
            "include_changelog": "false",
        }

        response = api_session.get(
            api_url,
            params=api_params,
            headers={"User-Agent": const.USER_AGENT},
            timeout=const.API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        if not data:
            raise ValueError(f"No files available for {version}")

        valid_versions = download_context.modpack_config.valid_versions
        valid_mod_versions = [
            version for version in data if version.get("version_type") in valid_versions
        ]

        if not valid_mod_versions:
            raise ValueError(f"Mod does not have any {valid_versions} releases.")
        latest_version = valid_mod_versions[0]

        if not (files := latest_version["files"]):
            raise ValueError("Target mod version contains no files.")

        target_file = next((file for file in files if file["primary"]), files[0])
        target_filename = target_file["filename"]
        target_url = target_file["url"]

        if not target_filename or not target_url:
            raise ValueError("Target mod has no filename or download URL")

    except requests.HTTPError as error:
        code = error.response.status_code if error.response is not None else "Unknown"
        download_context.failed_mods.append(
            {"slug": mod_slug, "cause": f"API HTTP Error Status: {code}"}
        )
        return []
    except ValueError as error:
        download_context.failed_mods.append({"slug": mod_slug, "cause": str(error)})
        return []

    collected_mods = [
        {"slug": mod_slug, "filename": target_filename, "url": target_url}
    ]

    resolved_dependencies = resolve_dependencies(
        latest_version, api_session, download_context
    )
    collected_mods.extend(resolved_dependencies)

    return collected_mods


def clear_jar_files(directory_path: Path) -> None:
    """Clears .jar files in the directory path. This is
    to prevent mod duplicates when downloading mods
    """
    files = directory_path.glob("*.jar")
    for file in files:
        try:
            file.unlink()
        except Exception as error:
            print(f"Could not remove {file}: {error}", style="error")


def _get_selected_launcher_path() -> Path | None:
    """
    NOTE: This function is a helper function for _get_download_folder_path()

    Scans the system for known launcher directory structures on Windows.
    If multiple launchers are found, prompts the user to select one or provide a
    custom directory path. Non-Windows systems default immediately to manual input.

    Returns:
        Path | None: Path if a launcher directory is found or provided
        None if the user is forced to provide a manual path.
    """
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
        return None

    launcher_choices: list[str] = [
        location
        for location, folderpath in folderpath_search_locations.items()
        if folderpath.exists()
    ]

    if not launcher_choices:
        return None

    if len(launcher_choices) > 1:
        launcher_choice = questionary.select(
            "Which launcher do you want to use to download the mods?",
            choices=launcher_choices + [questionary.Separator(), "Create Manual Path"],
        ).ask()
        if launcher_choice == "Create Manual Path":
            return None
    else:
        launcher_choice = launcher_choices[0]

    launcher_path = folderpath_search_locations[launcher_choice]
    return launcher_path


def _get_modpack_folder(launcher_path: Path) -> Path:
    """NOTE: This function is a helper function for get_download_folder_path()
    This gets and returns the selected modpack folder inside the launcher_path.

    Args:
        launcher_path (Path): launcher path given by the other helper function, _get_selected_launcher_path()
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
        choices=directories
        + [questionary.Separator(), "Create New Modpack Folder", "Enter Manual Path"],
        style=const.QUESTIONARY_STYLE,
    ).ask()

    if modpack_choice == "Create New Modpack Folder":
        modpack_name = questionary.text(
            "What should the name of the new modpack be?"
        ).ask()
        return launcher_path / modpack_name / "mods"

    elif modpack_choice == "Enter Manual Path":
        return enter_manual_path("Please enter the path for the new modpack folder:")

    return launcher_path / modpack_choice / "mods"


def get_download_folder_path(download_context: DownloadContext) -> Path:
    """
    Gets the download folder destination of the selected mods.
    Uses the default path in the configs instead if it exists.
    """
    if download_context.modpack_config.mods_directory is not None:
        return download_context.modpack_config.mods_directory

    while True:
        launcher_path = _get_selected_launcher_path()
        if launcher_path is None:
            return enter_manual_path()
        return _get_modpack_folder(launcher_path)


def enter_manual_path(
    prompt: str = "Please enter a path where mods will be downloaded:",
) -> Path:
    """This function prompts the user to enter a manual path, usually used if the smart
    directory finding system could not find one.

    This function also exits out of the program if no path is provided.
    """
    user_directory = prompt_user_for_directory(prompt=prompt)
    if not user_directory:
        print("No path provided, exiting program.", style="error")
        sysexit(1)
    return user_directory


def download_mods(
    modlist: list[dict[str, str]],
    api_session: requests.Session,
    download_context: DownloadContext,
) -> None:
    """
    Downloads mods in the modlist by fetching data from the mod's link. Also has progress bars.
    """
    while True:
        modpack_folderpath: Path = get_download_folder_path(download_context)
        confirm_folderpath = questionary.confirm(
            f"Is ({modpack_folderpath}) the correct filepath?",
            style=const.QUESTIONARY_STYLE,
        ).ask()
        if confirm_folderpath:
            break
        print("Alright, let's try that again then.", style="info")
        download_context.modpack_config.mods_directory = None
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

        def download_one_mod(target_mod: dict[str, str]) -> None:
            """Downloads the mod according to it's URL."""
            try:
                download_path = modpack_folderpath / target_mod["filename"]
                if not (url := target_mod.get("url")):
                    raise ValueError(f"{target_mod} has no url!")

                # requests does not support Path objects, therefore the url must be a string.
                response = api_session.get(
                    url,
                    stream=True,
                    timeout=const.API_TIMEOUT,
                    headers={"User-Agent": const.USER_AGENT},
                )
                response.raise_for_status()

                mod_filesize = int(response.headers.get("Content-Length", 0))

                with const.THREADING_LOCK:
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
                with const.THREADING_LOCK:
                    main_progress.update(mods_downloaded, advance=1)
                    mod_download_progress.remove_task(mod_downloading_progress_id)
            except requests.HTTPError as error:
                code = (
                    error.response.status_code
                    if error.response is not None
                    else "Unknown"
                )
                download_context.failed_mods.append(
                    {
                        "slug": target_mod.get("slug", "Unknown"),
                        "cause": f"API HTTP Error Status: {code}",
                    }
                )
            except ValueError as error:
                download_context.failed_mods.append(
                    {"slug": target_mod.get("slug", "Unknown"), "cause": str(error)}
                )

        # to not overwhelm the servers, ive capped it at 5
        # also makes it faster anyway so
        with ThreadPoolExecutor(max_workers=5) as executor:
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
# - make the detailed_logs config actually work
