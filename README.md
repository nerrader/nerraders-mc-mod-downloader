# Minecraft Mods Downloader

I made this tool to speed up and automate the usually tedious process of manually downloading mods for new minecraft versions.

This tool was developed with the Python library requests with the Modrinth API to fetch essential mod data. It also uses questionary to make the interactive CLI elements.

I've always spent one to two hours just searching up and downloading those mods just to play the game, so having a tool just automate it for me saves so much time.

![mc-mod-downloader-preview-optimized](https://github.com/user-attachments/assets/5e0a90df-2c89-4431-97c0-d369cda49d15)

# How to Download/Install

1. Download the latest .exe file in the releases
2. Run the .exe file
3. If Windows flags the .exe as unrecognized, click on **More Info > Run Anyway**
    > _This happens because this tool is new and does not have a paid Microsoft Developer Certificate._
4. You're done!

# How to Use

The only part where it might be slightly confusing is the part where you need to select the mods themselves, the rest is automated.

- **Arrow Keys** to move up and down the list.
- Then, you can choose a category to browse mods by.
- **Space** to select the mod for downloading
- **'A' Key** to select all in the current mod category (not recommended for first time users)
- **'I' Key** to invert your selections (swaps what is checked and unchecked)
- **Enter** to confirm your selection when you are done browsing mods in the category (or to exit the category)
- Repeat this process with multiple (or all) the categories until you are satisfied.
- When you're done, you can press enter on 'Finish and Download' to start the download process.

> [!CAUTION]
> Make sure you are choosing mods that match your Mod Loader (e.g., don't mix Fabric mods with a Forge installation).

### Mod Tags

If there are no tags on a mod in the main menu, it is a client side mod by default.

|    Tag     |     Meaning     |                                        Description                                         |
| :--------: | :-------------: | :----------------------------------------------------------------------------------------: |
|  **[S]**   |     Server      |                         Only needs to be installed on the server.                          |
| **[BOTH]** | Server & Client |            Recommended/Needed to be installed on both the server and the client            |
| **[DEV]**  |    Developer    |                  Usually used for developers/server owners/creative mode                   |
|  **[!]**   |     Caution     | May offer an unfair advantage, potential to you get banned from servers. Use with caution. |
