# BeamMP Manager

A configurable web-based manager for your BeamMP server using Discord as authentication.

> [!IMPORTANT]
> This script has only been tested on Linux, but it should work on Windows.
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
  * Edit the `config.json` (See [configuring](#configuring))

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
* Manage server settings
  * View and change server settings
  * Automatically detect maps in mods you upload
  * Autofilled options to change the map setting to
* Logging
  * Log player joins and leaves
  * Log when players finish downloading mods from the server
  * Log chat messages
  * Logs save across server restarts
* And More
  * Update server binary
  * User permission levels to manage dashboard access
  * Restart server
  * Manually reload mods
  * Send chat messages as the server

### **Planned Features**

* Uploading mods from the BeamNG repo
* Enhanced event logging (Server start/stop, dashboard logins, etc.)
* More methods of authentication (Google)
* Option to not automatically start the server (Maybe a process-detached read-only mode?)
 
### **Configuring**

`config.json` looks like this by default:
```
{
    "authorized_discord_users": {
        "-1": {
            "permissions": [
                "modify_settings",
                "modify_mods",
                "manage_server"
            ]
        }
    },
    "beammp_executable_path": "",
    "detect_mod_maps": true,
    "discord_oauth2_redirect_url": "",
    "maximum_log_entries": 500,
    "persist_data": true,
    "preserve_setting_changes": true,
    "public_dashboard": true,
    "url_base_path": "/beammp",
    "virustotal_scanning": true
}
```
**authorized_users** - An array of Discord user IDs who will be able to login to the web manager. Each Discord user ID has an array that has a `permissions` list. The possible permissions a user can have are `modify_settings`, `modify_mods`, `manage_server`, `clear_logs`, and `configure`.

**beammp_executable_path** - The path to your BeamMP Server executable. This should be located within the same directory as main.py.

**detect_mod_maps** - Whether uploaded mods are scanned for modded levels. If found, the level filepath will automatically be saved (if persist_data is enabled) and available in the settings dropdown.

**discord_oauth2_redirect_url** - The public URL to the web manager's `/login/oauth2` page. This URL must be added on the Discord Developer Portal under OAuth2.

**maximum_log_entries** - The maximum number of total log entries that will be stored. This is useful to limit the file size of the persistent data file.

**persist_data** - Whether data such as logs and detected level filepaths should persist across manager restarts.

**preserve_setting_changes** - Whether setting changes should be saved to the ServerConfig.toml file. If not, setting changes will be cleared after a BeamMP server restart.

**public_dashboard** - Whether the public mod dashboard is enabled. If disabled, the guest login button and associated pages will be disabled.

**url_base_path** - The base path to use for accessing the web manager. This is useful if you run multiple web services on the same URL, otherwise you can just set this to `/`.

**virustotal_scanning** - Whether mod uploads should be scanned by VirusTotal before they are added to the server. Set to `false` if you do not have a VirusTotal API key.

> [!IMPORTANT]
> BeamMP-Manager is not affiliated or endorsed in any way by BeamMP or BeamNG Gmbh.
