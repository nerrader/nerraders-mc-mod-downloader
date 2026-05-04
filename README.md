# Minecraft Mods Downloader

I made this tool to significantly speed up and automate the usually tedious process of manually searching up and downloading minecraft mods.

This tool was developed with the Python library requests with the Modrinth API to fetch essential mod data. It also uses questionary to make the interactive CLI elements.

I've always spent one to two hours just searching up and downloading those mods just to play the game, and this is especially true for migrating minecraft versions due to servers updating and whatnot, so having a tool just automate it for me saves so much time.

![mc-mod-downloader-preview-optimized](https://github.com/user-attachments/assets/5e0a90df-2c89-4431-97c0-d369cda49d15)

# Features

- ### Interactive CLI Elements
    This tool uses questionary to make this CLI tool easier to use and more interactive.

- ### Automatic Dependency Resolution
    This tool scans the mods to see if it requires any depedencies, and automatically downloads them too. 

- ### Extremely Fast Download Speeds
    This tool uses API Sessions and Multithreadding to significantly speed up the process of fetching mod data and downloading.

- ### Incompatible Mod Safety
    This tool safely ignores and filters the mods that are not compatible with your selected mod loader and game version in the settings, the incompatible mods will then be put in a summary at the end of the downloading process for you to see for yourself.

- ### Customizable
    You can customize settings and how this tool interacts in the main menu

# How to Download/Install

> [!NOTE]
> Before using this tool, make sure you have:
> - Windows 10 or more (this doesn't work on other OSes)
> - Stable internet connection (for the app/tool to run properly)
> - Proper installation of Minecraft, or any other launcher (a place for mods to download)

1. **Download** the latest .zip folder from the latest [Release](https://github.com/nerrader/nerraders-mc-mod-downloader/releases)
2. **Extract** the **.zip folder**
3. Run the .exe file inside that folder
> [!important]
> If Windows flags the .exe as unrecognized, click on **More Info > Run Anyway**
> 
> This happens because this tool is new and does not have a paid Certificate. That would cost me $200/year to sign.
> 
> Here's a [VirusTotal scan](https://www.virustotal.com/gui/file/0715d68d44ee76ea12aa96c12561cefab7cdd1c2049f4a718f36cdd5ea1fa974?nocache=1) I did on my own .exe as of v3.1.1.
>
> If you are still curious or still skeptical of the safety of the .exe, feel free to run your own VirusTotal scan, or just check the source code that is available right here on GitHub. Everything's open source.
4. You're done!

# How to Use

> [!important]
These instructions are for users who are using the latest version of the `mc-mod-downloader`, if you are using an older version, some features may be unavailable, or the process may differ. I recommend updating this tool to the latest version for the best experience.

The only part where it might be slightly confusing is the part where you need to select the mods themselves, as the rest of the tool is automated.

> [!NOTE]
> This tool creates a directory in AppData/Roaming/mc-mods-downloader to store, and sometimes modfiy needed .json files for it to function.

- **Arrow Keys** to move up and down the list.
- Then, you can choose a category to browse mods by.
- **Space** to select the mod for downloading
- **'A' Key** to select all in the current mod category (not recommended for first time users)
- **'I' Key** to invert your selections (swaps what is checked and unchecked)
- **Enter** to confirm your selection when you are done browsing mods in the category (or to exit the category)
- Repeat this process with multiple (or all) the categories until you are satisfied.
- When you're done, you can press enter on 'Finish and Download' to start the download process.

> [!TIP] 
> Make sure to check and configure your settings to your liking before starting the download process, as defaults might be undesirable.
>
> #### Default Settings:
> | Setting/Config | Default Value | Description |
> | :--------: | :------------: | :---: |
> | Mod Loader | Fabric | Mods meant for other loaders like Forge will be skipped |
> | Game Version | Latest Release | Snapshots, alpha and beta versions do not count |
> | Valid Versions | Release | This means that alpha/beta mod versions will not get downloaded |
> | Auto Clear Jars | False | Requires confirmation before clearing all .jars |
> | Show Detailed Logs | False | (Planned) Logs more of the tools whereabouts and what its doing that are usually hidden to the average user |

### Mod Tags

If there are no tags on a mod in the main menu, it is a client side mod by default.

|    Tag     |     Meaning     |                                        Description                                         |
| :--------: | :-------------: | :----------------------------------------------------------------------------------------: |
|  **[S]**   |     Server      |                         Only needs to be installed on the server.                          |
| **[BOTH]** | Server & Client |            Recommended/Needed to be installed on both the server and the client            |
| **[DEV]**  |    Developer    |                  Usually used for developers/server owners/creative mode                   |
|  **[!]**   |     Caution     | May offer an unfair advantage, potential to you get banned from servers. Use with caution. |

# Upcoming/Planned Features

Here are some features that will be planned for future major/minor releases.

- Import/Export Modlists to ensure consistency across mod downloads and to pre-select mods.
- Using asyncio to replace mutli threadding as it is faster and more reliabl for these tasks.
- Further refactoring of main.py into other folders to make code and documentation easier to read.
- Logging and verbose mode
- Adding more mods, mod categories and settings to make this tool even more customizable.
- Compatibility with other OSes

# Contributing

This project welcomes all contributors, and whether you are fixing a bug, adding a new feature, or just improving the documentation of this project, you can get started by just following these steps:

1. Fork this repository
2. Clone this repository on your computer `git clone https://github.com/YOUR-USERNAME/nerraders-mc-mod-downloader.git`
3. It is recommended that you make a seperate branch than the main branch `git switch -c feature/new-feature`, using `feature/` for new features, and `fix/` to fix a known issue/bug, just to name a few.
4. Use `uv sync` to automatically set up the virtual environment and grab all the dependencies for you.
5. Commit your changes. Make sure your commit messages are clear and concise.
6. Push changes to your fork of the repository
7. Open a pull request. If you go back to the original repository, there should be a button called Compare & Pull Request. Click it, and one should be automaticallly made for you. Describe your changes and why they should be implemented in the main repository, then submit.

> [!IMPORTANT]
> Please make sure your code works properly before submitting. Follow PEP 8 guidelines, maintain consistent styling, and include type annotations and documentation for any new functions.

By contributing this project, you agree that your contribution will be licensed under its MIT License.
