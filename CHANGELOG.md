# v3.0.0 - 03-04-2026
- Huge code polishing and refactor, removed the need for global variables, put constants in constants.py, and so much more.
- Uses rich.live to improve and polish the progress bars during downloading.
- Polished the UX of getting the user's download folder path.
- Added a summary table for the failed/incompatible mods at the end.
- Added a MIT License
- Added bandit, radon and vulture dev dependencies to speed up the future development of this project.
- Now uses the hatchling build system for packaging.
# v2.0.0 - 26-03-2026
- Introduced multithreadding to significantly speed up the tools moddata fetching and downloading processes
- Added progress bars to visualize the progress during the downloading section.
- Changed library mods in mods.json to be a list of slugs, as it wasn't required to be in the main menu anymore.
- Slightly changed and improved documentation across main.py
# v1.2.0 - 23-03-2026
- Now uses persistent API Sessions to make this tool significantly faster by removing the need to do a TCP handshake at the beginning of each.
# v1.1.0 - 22-03-2026
- Initial release of this tool (v1.0.0 disappeared)
- Added core features for the tool such as the main menu, settings/configs, initial fetching and downloading process of mods.
