from copy import deepcopy
from dataclasses import dataclass, asdict, fields
from pathlib import Path

from loguru import logger
import questionary
import requests

from mc_mods_downloader import constants as const, storage
from mc_mods_downloader.utils.prompt_user_for_directory import prompt_user_for_directory

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
    def load_configs(cls) -> "Config":
        """Returns a config class according to the configs in config.json."""
        logger.info("Loading configs from config.json")
        configs = storage.load_json(const.CONFIG_FILEPATH)
        return cls(
            configs["version"],
            configs["mod_loader"],
            configs["valid_versions"],
            Path(configs["mods_directory"]) if configs["mods_directory"] else None,
            BehaviourConfig(**configs["behaviour_settings"]),
        )

    @classmethod
    def get_default_config(
        cls, api_session: requests.Session | None = None
    ) -> "Config":
        """Gets and returns a config class with the defaults.
        Uses the Modrinth API to get the latest major minecraft version."""
        logger.info("Generating default config")

        minecraft_versions = get_all_minecraft_versions(api_session)
        logger.debug(
            f"Successfully extracted {len(minecraft_versions)} release versions."
        )
        # pretty much guaranteed to succeed unless bad internet or server crash, so no try except

        latest_minecraft_version = minecraft_versions[0]
        return cls(
            version=latest_minecraft_version,
            mod_loader="fabric",
            valid_versions=["release"],
            mods_directory=Path(""),
            behaviour_settings=BehaviourConfig(False, False),
        )

    @classmethod
    def get_or_create_config(
        cls, api_session: requests.Session | None = None
    ) -> "Config":
        """Checks if config.json exists. Loads it if it does,
        or generates, saves, and returns a default one if it doesn't.
        """
        logger.info("Checking for existing config file")
        if not const.CONFIG_FILEPATH.exists():
            logger.info("Config file not found, generating default config")
            default_config = cls.get_default_config(api_session)
            default_config.save_configs()
            return default_config

        logger.info("Config file found, loading contents from it instead")
        return cls.load_configs()

    def save_configs(self) -> None:
        logger.info("Saving configs to config.json")
        configs = asdict(self)
        configs["mods_directory"] = (
            str(configs["mods_directory"])
            if isinstance(configs["mods_directory"], Path)
            else None
        )
        storage.write_json(const.CONFIG_FILEPATH, configs)


def get_all_minecraft_versions(
    api_session: requests.Session | None = None,
) -> list[str]:
    api_url = "https://api.modrinth.com/v2/tag/game_version"
    session = api_session or requests
    headers = {"User-Agent": const.USER_AGENT} if not api_session else None
    data = session.get(api_url, timeout=const.API_TIMEOUT, headers=headers).json()
    return [
        version["version"] for version in data if version["version_type"] == "release"
    ]


def _change_minecraft_version(config: Config) -> str:
    logger.info("Changing Minecraft version")
    original_version = config.version

    minecraft_versions = get_all_minecraft_versions()

    print("Tip: Press Tab to enable autocomplete", style="warning")
    selected_version = questionary.autocomplete(
        "Type your minecraft version (e.g. 1.21): ",
        choices=minecraft_versions,
        default=config.version,
    ).ask()

    # if user cancells using CTRL + C
    if selected_version is None:
        logger.info("Minecraft version change cancelled by user.")
        return original_version

    logger.info(f"Selected minecraft version: {selected_version}")
    return selected_version


def _change_mod_loader(config: Config) -> str:
    logger.info("Changing mod loader")

    original_mod_loader = config.mod_loader

    print("Note that all Quilt users can use Fabric mods.", style="info")
    selected_mod_loader = questionary.select(
        "Choose your mod loader:",
        choices=("Fabric", "Neoforge", "Forge"),
        default=config.mod_loader.capitalize(),
        style=const.QUESTIONARY_STYLE,
    ).ask()

    if selected_mod_loader is None:
        logger.info("Mod loader change cancelled by user.")
        return original_mod_loader

    logger.info(f"Selected mod loader: {selected_mod_loader}")
    return selected_mod_loader


def _select_valid_versions(config: Config) -> list[str]:
    logger.info("Selecting valid versions")

    original_valid_versions = config.valid_versions.copy()

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

    if selected_valid_versions is None:
        logger.info("Valid versions selection cancelled by user.")
        return original_valid_versions

    logger.info(f"Valid versions selected: {', '.join(selected_valid_versions)}")
    return selected_valid_versions


def _change_default_path(config: Config) -> Path | None:
    return prompt_user_for_directory(
        mods_directory=config.mods_directory or const.HOME_FILEPATH
    )


def _change_behaviour_settings(config: Config) -> None:
    logger.info("Changing behaviour settings")

    behaviour_config_names: list[str] = [
        field.name for field in fields(config.behaviour_settings)
    ]
    print(
        "NOTE: Verbose Mode will only be turned on the next time you run the program.",
        style="info",
    )
    selected = questionary.checkbox(
        "Behaviour Settings:",
        choices=[
            questionary.Choice(
                title=setting.replace("_", " ").title(),
                value=setting,
                checked=getattr(config.behaviour_settings, setting),
            )
            for setting in behaviour_config_names
        ],
        style=const.QUESTIONARY_STYLE,
    ).ask()

    # helps deal with Ctrl + C cancellation
    # this one modifies the config directly so you can just return instead of returning the original
    if selected is None:
        logger.info("Behaviour settings change cancelled by user.")
        return

    # turns all the config true if selected otherwise false
    for behaviour_setting in behaviour_config_names:
        if behaviour_setting in selected:
            logger.info(f"Enabled behaviour setting: {behaviour_setting}")
            setattr(config.behaviour_settings, behaviour_setting, True)
            continue
        logger.info(f"Disabled behaviour setting: {behaviour_setting}")
        setattr(config.behaviour_settings, behaviour_setting, False)


def main_settings_loop(original_config: Config) -> Config:
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
                logger.info("Saving settings and exiting settings menu.")
                new_config.save_configs()
                logger.success("Settings saved successfully.")
                return new_config
            case "Cancel":
                logger.info(
                    "Settings changes cancelled by user, exiting settings menu."
                )
                return original_config
