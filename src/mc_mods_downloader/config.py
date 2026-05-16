from copy import deepcopy
from dataclasses import dataclass, asdict, fields
from pathlib import Path

import questionary
import requests

from mc_mods_downloader import constants as const, storage

print = const.CONSOLE.print


@dataclass
class BehaviourConfig:
    auto_clear_jars: bool
    verbose_mode: bool


@dataclass
class Config:
    version: str
    mod_loader: str
    valid_versions: list[str]
    mods_directory: Path | None
    behaviour_settings: BehaviourConfig

    @classmethod
    def load_configs(cls):
        """Returns a config class according to the configs in config.json."""
        configs = storage.load_json(const.CONFIG_FILEPATH)
        return cls(
            configs["version"],
            configs["mod_loader"],
            configs["valid_versions"],
            Path(configs["mods_directory"]) if configs["mods_directory"] else None,
            BehaviourConfig(**configs["behaviour_settings"]),
        )

    @classmethod
    def get_default_config(cls, api_session: requests.Session | None = None):
        """Gets and returns a config class with the defaults.
        Uses the Modrinth API to get the latest major minecraft version."""

        api_url = "https://api.modrinth.com/v2/tag/game_version"
        requests_session = api_session or requests
        headers = {"User-Agent": const.USER_AGENT} if not api_session else None
        data = requests_session.get(
            api_url, timeout=const.API_TIMEOUT, headers=headers
        ).json()

        # pretty much guaranteed to succeed unless bad internet or server crash, so no try except
        minecraft_versions = [
            version["version"]
            for version in data
            if version["version_type"] == "release"
        ]
        latest_minecraft_version = minecraft_versions[0]
        return cls(
            version=latest_minecraft_version,
            mod_loader="fabric",
            valid_versions=["release"],
            mods_directory=Path(""),
            behaviour_settings=BehaviourConfig(False, False),
        )

    def save_configs(self) -> None:
        configs = asdict(self)
        configs["mods_directory"] = (
            str(configs["mods_directory"])
            if isinstance(configs["mods_directory"], Path)
            else None
        )
        storage.write_json(const.CONFIG_FILEPATH, configs)


def _change_minecraft_version(config: Config) -> str:
    api_url: str = "https://api.modrinth.com/v2/tag/game_version"
    data = requests.get(
        api_url, timeout=const.API_TIMEOUT, headers={"User-Agent": const.USER_AGENT}
    ).json()  # pretty much guaranteed to be 200, no try except needed

    minecraft_versions = [
        version["version"] for version in data if version["version_type"] == "release"
    ]

    print("Tip: Press Tab to enable autocomplete", style="warning")
    selected_version = questionary.autocomplete(
        "Type your minecraft version (e.g. 1.21): ",
        choices=minecraft_versions,
        default=config.version,
    ).ask()

    return selected_version


def _change_mod_loader(config: Config) -> str:
    print("Note that all Quilt users can use Fabric mods.", style="info")
    selected_mod_loader = questionary.select(
        "Choose your mod loader:",
        choices=("Fabric", "NeoForge", "Forge"),
        default=config.mod_loader,
        style=const.QUESTIONARY_STYLE,
    ).ask()
    return selected_mod_loader


def _select_valid_versions(config: Config) -> list[str]:
    selected_valid_versions = questionary.checkbox(
        "Which mod versions do you allow?",
        choices=(
            questionary.Choice(
                title="Release (Stable)",
                value="release",
                checked="release" in config.valid_versions,
            ),
            questionary.Choice(
                title="Beta (Testing)",
                value="beta",
                checked="beta" in config.valid_versions,
            ),
            questionary.Choice(
                title="Alpha (Early Development, NOT RECOMMENDED)",
                value="alpha",
                checked="alpha" in config.valid_versions,
            ),
        ),
        default="release",
        style=const.QUESTIONARY_STYLE,
    ).ask()
    return selected_valid_versions


def _change_default_path(config: Config) -> Path | None:
    print(
        "Note that changing this setting will remove the pathing prompt when downloading",
        style="warning",
    )
    print(
        "Tip: You can copy and paste the path from the file explorer search bar",
        style="warning",
    )
    selected_folder_path: str = questionary.path(
        "Change Default Mods Path: (press tab)",
        default=str(config.mods_directory) if config.mods_directory else "",
        style=const.QUESTIONARY_STYLE,
    ).ask()
    return (
        Path(selected_folder_path)
        if not selected_folder_path or selected_folder_path == "None"
        else None
    )


def _change_behaviour_settings(config: Config) -> None:
    behaviour_config_names: list[str] = [
        field.name for field in fields(config.behaviour_settings)
    ]
    selected = questionary.checkbox(
        "Behaviour Settings:",
        choices=[
            questionary.Choice(
                title=setting.lower().replace("_", " "),
                value=setting,
                checked=getattr(config.behaviour_settings, setting),
            )
            for setting in behaviour_config_names
        ],
        style=const.QUESTIONARY_STYLE,
    ).ask()

    # helps deal with Ctrl + C cancellation
    if not selected:
        return

    # turns all the config true if selected otherwise false
    for behaviour_setting in behaviour_config_names:
        if behaviour_setting in selected:
            setattr(config.behaviour_settings, behaviour_setting, True)
            continue
        setattr(config.behaviour_settings, behaviour_setting, False)


def main_settings_loop(original_config: Config) -> Config:
    """The main setting configuration menu."""
    new_config: Config = deepcopy(original_config)

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
            style=const.QUESTIONARY_STYLE,
        ).ask()

        match choice:
            case "Change Minecraft Version":
                new_config.version = _change_minecraft_version(new_config)
            case "Change Mod Loader":
                new_config.mod_loader = _change_mod_loader(new_config)
            case "Select Valid Versions":
                new_config.valid_versions = _select_valid_versions(new_config)
            case "Set Default Folder Path":
                new_config.mods_directory = _change_default_path(new_config)
            case "Behaviour Settings":
                _change_behaviour_settings(new_config)  # this one changes it directly
            case "Reset Settings to Default":
                new_config = Config.get_default_config()
            case "Exit and Save":
                new_config.save_configs()
                return new_config
            case "Cancel":
                return original_config
