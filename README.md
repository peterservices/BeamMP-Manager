# BeamMP Manager

A configurable web-based manager for your BeamMP server using Discord as authentication.

> [!IMPORTANT]
> This script has only been tested with Linux.
> 
> This script is intended for managing a BeamMP server on a remote server. It is recommended to configure this behind a reverse proxy such as [Nginx](https://nginx.org/).

### **Prerequisites**

* Be able to run a standalone [BeamMP Server](https://github.com/BeamMP/BeamMP-Server)
* Have the client ID and client secret of your [Discord App/Bot](https://discord.com/developers/applications)
* Install [uv](https://docs.astral.sh/uv/getting-started/installation/#__tabbed_1_2) OR a standalone compatible Python version
  * [uv] Install a compatible version of Python using the terminal (ex: `uv python install 3.13`)
* [Optional] Have a [VirusTotal](https://www.virustotal.com) API key

### **Quickstart Guide**

* Clone or [download the source](https://github.com/peterservices/BeamMP-Manager/archive/refs/heads/main.zip) and place the uncompressed folder in a convenient location
  * Install dependencies (With uv: Use uv in the terminal. ex: `uv sync`)
* Download or compile a [BeamMP Server](https://github.com/BeamMP/BeamMP-Server) executable, and put it in the same directory as BeamMP-Manager
* Copy the contents of `.env.example` and create a file named `.env`
  * Add your Discord App's client ID and client secret, as well as your VirusTotal API key if you have one (SECRET_KEY will be auto-filled, or you can generate your own)
* Run the web server in the terminal with `.venv/bin/python -m hypercorn --bind 0.0.0.0:30815 main.py` (Replace 30815 with whatever port you prefer that is port-forwarded)
  * Edit the `config.json`
 
### **Configuring**

`config.json` contains the following fields:
```
{
     "beammp_executable_path": "",
     "url_base_path": "/beammp",
     "discord_oauth2_redirect_url": "",
     "virustotal_scanning": true,
     "preserve_settings_changes": true,
     "detect_mod_maps": true,
     "public_dashboard": true,
     "levels": [...],
     "authorized_users": []
}
```
beammp_executable_path - The path to your BeamMP Server executable. This should be located within the same directory.

url_base_path - The base path to use for accessing the web manager. This is useful if you run multiple web services on the same URL.

discord_oauth2_redirect_url - The public URL to the web manager's `/login/oauth2` page. This URL must be added on the Discord Developer Portal under OAuth2.

virustotal_scanning - Whether mod uploads should be checked by VirusTotal before they are added to the server. Set to `false` if you do not have a VirusTotal API key.

preserve_settings_changes - Whether setting changes should be saved to the ServerConfig.toml file. Otherwise, changes will be cleared after a server restart.

detect_mod_maps - If enabled, when mods are uploaded they will be scanned for modded levels. If found, the level will automatically be added to `levels` and available in the settings dropdown.

public_dashboard - Whether the public mod dashboard is enabled. If disabled, the guest login button and associated pages will be disabled.

levels - A list of filepaths to maps that will be available in the settings dropdown. This field is auto-populated with the default BeamNG maps.

authorized_users - A list of Discord user IDs of the users who should be able to login to the web manager.

### **Features**

* Public Dashboard (No login necessary)
  * View and download mods
  * Can be turned off if desired
* Mod Management
  * View and download mods
  * Upload mods
  * Disable mods
  * Delete mods
* Player Management
  * View online players
  * Kick players
* Logging
  * Log player joins and leaves
  * Log when players finish downloading mods from the server
  * Log chat messages
* And More
  * View and change server settings
  * Restart server
  * Manually reload mods
  * Send chat messages as the server


### **Planned Features**

* Map setting dropdown
* Historical logs that save over restarts
* More methods of authentication (Google)
* Permission levels
* Option to not automatically start the server (Maybe a process-detached read-only mode?)

> [!IMPORTANT]
> BeamMP-Manager is not affiliated or endorsed in any way by BeamMP or BeamNG Gmbh.
