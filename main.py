import asyncio
import contextlib
import datetime
import json
import logging
import os
import platform
import re
import shutil
import signal
import stat
import zipfile
from functools import wraps
from secrets import token_urlsafe
from typing import Any, Literal

import aiofiles
import aiofiles.os as aioos
import aiohttp
import discordoauth2
import tomlkit
import vt
from dotenv import find_dotenv, load_dotenv, set_key
from quart import (
    Quart,
    Response,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    send_file,
    session,
    websocket,
)
from quart_auth import (
    AuthUser,
    QuartAuth,
    Unauthorized,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from werkzeug.datastructures import FileStorage
from werkzeug.utils import safe_join, secure_filename

from models import (
    Broker,
    LocalConfiguration,
    PersistentData,
    ReleaseCache,
    ReleaseFile,
    ServerData,
    ServerSettings,
    TempFile,
)

logging.basicConfig(level=logging.DEBUG, format="[BeamMP Manager] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BEAMPAINT_MAIN_LUA = "https://cdn.beampaint.com/api/v2/download/release/updater/main.lua"
BEAMMP_GITHUB_RELEASE = "https://api.github.com/repos/BeamMP/BeamMP-Server/releases/latest"

DOTENV_PATH = find_dotenv()
load_dotenv(dotenv_path=DOTENV_PATH)

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

SECRET_KEY = os.getenv("SECRET_KEY")
if SECRET_KEY is None or len(SECRET_KEY) == 0:
    SECRET_KEY = token_urlsafe() # Generate a new SECRET_KEY
    if DOTENV_PATH != "":
        set_key(DOTENV_PATH, "SECRET_KEY", SECRET_KEY) # Save the SECRET_KEY to preserve sessions across restarts

VT_KEY = os.getenv("VT_KEY")

app = Quart(__name__)
app.secret_key = SECRET_KEY

QuartAuth(app, duration=30 * 24 * 60 * 60)

configuration = LocalConfiguration()
if not os.path.exists("config.json"):
    to_write = configuration.model_dump_json(indent=4)
    with open("config.json", "x") as file:
        file.write(to_write)
else:
    with open("config.json") as file:
        config_str = file.read()
    configuration = LocalConfiguration.model_validate_json(config_str)
    if configuration and os.path.exists(configuration.beammp_executable_path):
        configuration.beammp_executable_path = os.path.abspath(configuration.beammp_executable_path)

    # Save any new changes to disk
    json_data = configuration.model_dump_json(indent=4)
    if json_data != config_str:
        to_write = json_data
        with open("config.json", "w") as file:
            file.write(to_write)

if configuration.require_login:
    if CLIENT_ID is None or len(CLIENT_ID) == 0 or CLIENT_SECRET is None or len(CLIENT_SECRET) == 0:
        raise KeyError("Both the CLIENT_ID and CLIENT_SECRET environment variables are required for Discord login.")
else:
    logger.warning("Operating without a login requirement! If this server is exposed to the public internet, anyone can manage your server!")

persistent_data = PersistentData()
if configuration.persist_data:
    if not os.path.exists("persistent_data.json"):
        to_write = configuration.model_dump_json(indent=4)
        with open("persistent_data.json", "x") as file:
            file.write(to_write)
    else:
        with open("persistent_data.json") as file:
            persistent_str = file.read()
        persistent_dict = json.loads(persistent_str)
        persistent_dict["lock"] = persistent_data.lock
        persistent_data = PersistentData.model_validate(persistent_dict)

        # Save any new changes to disk
        json_data = persistent_data.model_dump_json(indent=4)
        if json_data != persistent_str:
            to_write = json_data
            with open("persistent_data.json", "w") as file:
                file.write(to_write)

if configuration.require_login:
    oauth_client = discordoauth2.AsyncClient(id=CLIENT_ID, secret=CLIENT_SECRET, redirect=configuration.discord_oauth2_redirect_url, bot_token="")

server_data = ServerData(persistent_data=persistent_data)
server_settings = ServerSettings()
release_cache: ReleaseCache = ReleaseCache()
temp_files: dict[str, TempFile] = {}
state_lock: asyncio.Lock = asyncio.Lock()
server_executable_lock: asyncio.Lock = asyncio.Lock()
temp_files_lock: asyncio.Lock = asyncio.Lock()
broker = Broker()
websockets: list[asyncio.Task] = []
log_file_position: int = 0

uname_result = platform.uname()
if uname_result.system.lower() == "windows":
    architecture = "exe"
elif uname_result.machine == "aarch64":
    architecture = "aarch64 / arm64"
else:
    architecture = uname_result.machine

async def run_command(command_str: str) -> None:
    """
    Send a command to the BeamMP server.
    """
    if server_data.process is None:
        return
    command_str = command_str + "\n"
    command = command_str.encode()
    server_data.process.stdin.write(command)
    await server_data.process.stdin.drain()

async def send_changed_data(old_data: ServerData, old_settings: ServerSettings | None = None) -> None:
    changes = {}
    server_data_dict = server_data.model_dump()
    old_data_dict = old_data.model_dump()
    for key in old_data_dict:
        if server_data_dict[key] != old_data_dict[key]:
            changes[key] = server_data_dict[key]
    if len(changes) != 0:
        await broker.event(changes)

    if old_settings is None:
        return

    changes = {}
    server_settings_dict = server_settings.model_dump()
    old_settings_dict = old_settings.model_dump()
    for key in server_settings_dict:
        if key not in old_settings_dict or server_settings_dict[key] != old_settings_dict[key]:
            changes[key] = server_settings_dict[key]
    if len(changes) != 0:
        changes["type"] = "settings"
        await broker.event(changes)

def reset_server_data() -> None:
    """
    Reset server_data to its default state.
    """
    global server_data
    server_data = ServerData(persistent_data=persistent_data)

def reset_server_settings() -> None:
    """
    Clear all settings from server_settings.
    """
    global server_settings
    server_settings = ServerSettings()

def snapshot_server_data() -> ServerData:
    old_data_json = server_data.model_dump_json() # We must dump the ServerData model first to avoid trying to copy a Process object, which will hang
    old_data = ServerData.model_validate_json(old_data_json)
    old_data.persistent_data = server_data.persistent_data.model_copy(deep=True)
    return old_data

def snapshot_settings() -> ServerSettings:
    return server_settings.model_copy(deep=True)

async def verify_persistent_fields() -> None:
    """
    Verify all the fields in persistent_data, and update the disk (if enabled) and websocket if changes were made.
    """
    old_data = snapshot_server_data() # Save old data to compare with after verifying levels
    levels = await server_data.persistent_data.verify_levels() if configuration.detect_mod_maps else False
    if levels or await server_data.persistent_data.trim_logs(configuration.maximum_log_entries):
        if configuration.persist_data:
            await server_data.persistent_data.dump_and_write()
        await send_changed_data(old_data)

async def update_release_cache() -> bool:
    """
    Fetches the latest release information from GitHub and updates the cache. Returns whether the update was successful.
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(BEAMMP_GITHUB_RELEASE) as response:
            if response.status < 200 or response.status >= 300:
                return False
            response_json: dict[str, Any] = await response.json()
    if "tag_name" not in response_json or "assets" not in response_json:
        return False
    release_cache.files.clear()
    release_cache.version = response_json["tag_name"]
    for asset in response_json["assets"]:
        if "name" not in asset or "size" not in asset or "browser_download_url" not in asset:
            continue
        name = asset["name"].split(".")
        if name[0] != "BeamMP-Server":
            continue
        platform = "windows" if "exe" in name else ".".join(name[1:-1])
        architecture = name[-1]
        file = ReleaseFile(platform=platform, architecture=architecture, download_url=asset["browser_download_url"], size=asset["size"])
        release_cache.files.append(file)
    return True

def user_has_permissions(user: AuthUser, permissions: list) -> bool:
    if not configuration.require_login:
        return True # Without a login requirement, the user is assumed to have full permissions.
    auth_id = int(user.auth_id)
    for permission in permissions:
        if permission not in configuration.authorized_discord_users.get(auth_id).permissions:
            return False
    return True

async def start_server() -> None:
    """
    Start the BeamMP Server.
    """
    global log_file_position
    async with state_lock:
        old_data = snapshot_server_data()
        try:
            async with aiofiles.open("Server.log", "w") as file:
                await file.writelines("")
        except OSError as e:
            logger.exception("Could not open and write to Server.log")
            raise e
        log_file_position = 0
        if configuration.persist_data:
            await verify_persistent_fields()
        reset_server_settings()
        reset_server_data()
        if await aioos.path.exists(configuration.beammp_executable_path):
            try:
                server_data.process = await asyncio.subprocess.create_subprocess_exec(configuration.beammp_executable_path, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, stdin=asyncio.subprocess.PIPE)
                server_data.started = True
            except (PermissionError, OSError):
                server_data.error = True
                logger.exception("Failed to start BeamMP server")
        server_data.beampaint_installed = await aioos.path.exists("Resources/Server/BeamPaintUpdater/")
        await send_changed_data(old_data)

async def write_config() -> None:
    """
    Write the configuration to disk asynchronously.
    """
    to_write = configuration.model_dump_json(indent=4)
    async with aiofiles.open("config.json", "w") as file:
        await file.write(to_write)

def authorization_required(required_permissions: list[str] = []):
    """
    Ensures the user is logged in and is an authorized user.
    """
    def decorator(func):
        @wraps(func)
        @login_required
        async def login_wrapper(*args, **kwargs):
            if int(current_user.auth_id) not in configuration.authorized_discord_users:
                raise Unauthorized()

            if not user_has_permissions(current_user, required_permissions):
                return abort(403)

            return await current_app.ensure_async(func)(*args, **kwargs)

        @wraps(func)
        async def open_wrapper(*args, **kwargs):
            return await current_app.ensure_async(func)(*args, **kwargs)

        if not configuration.require_login:
            return open_wrapper
        return login_wrapper
    return decorator

# -- Website routes --

@app.route(f"{configuration.url_base_path}/")
async def main_page():
    return redirect(f"{configuration.url_base_path}/dashboard")

@app.route(f"{configuration.url_base_path}/dashboard")
@authorization_required()
async def dashboard():
    return await render_template("dashboard.html", base=configuration.url_base_path)

@app.route(f"{configuration.url_base_path}/guest_dashboard")
async def guest_dashboard():
    if not configuration.public_dashboard or not configuration.require_login:
        return abort(404)
    return await render_template("guest_dashboard.html", base=configuration.url_base_path)

@app.route(f"{configuration.url_base_path}/mods_list")
async def guest_mods():
    if not configuration.public_dashboard or not configuration.require_login:
        return abort(404)
    mods = None
    async with aiofiles.open("Resources/Client/mods.json") as file:
        mods: dict[str, dict[str]] | None = json.loads(await file.read())
    if mods is not None:
        for _, mod in mods.items():
            mod.pop("hash")
            mod.pop("lastwrite")
            mod.pop("protected")
    else:
        mods = {}
    return mods

@app.route(f"{configuration.url_base_path}/login")
async def login():
    if not configuration.require_login:
        return abort(404)
    error = session.get("error", "")
    if "error" in session:
        session.pop("error")
    return await render_template("login.html",
                                 base=configuration.url_base_path,
                                 error=error,
                                 disabled_class=("" if configuration.public_dashboard else "disabled"),
                                 disabled_inert=("" if configuration.public_dashboard else "inert"),
                                 disabled_aria=("false" if configuration.public_dashboard else "true")
                                 )

@app.route(f"{configuration.url_base_path}/login/uri")
async def login_uri():
    if not configuration.require_login:
        return abort(404)
    uri = oauth_client.generate_uri(skip_prompt=True, scope=["identify"])
    return redirect(uri)

@app.route(f"{configuration.url_base_path}/login/oauth2")
async def oauth_login():
    if not configuration.require_login:
        return abort(404)
    session.permanent = True
    app.permanent_session_lifetime = datetime.timedelta(seconds=30) # Makes "error" session key automatically expire after 30 seconds
    session["error"] = "error"

    code = request.args.get("code")
    if code is None:
        return redirect(f"{configuration.url_base_path}/login")

    access = await oauth_client.exchange_code(code)
    identify = await access.fetch_identify()
    if "id" in identify:
        if int(identify["id"]) in configuration.authorized_discord_users:
            auth = AuthUser(auth_id=identify["id"])
            login_user(auth, True)
            session.pop("error")
            return redirect(f"{configuration.url_base_path}/dashboard")
        session["error"] = "unauthorized"
    return redirect(f"{configuration.url_base_path}/login")

@app.route(f"{configuration.url_base_path}/logout")
async def logout():
    if not configuration.require_login:
        return abort(404)
    logout_user()
    return redirect(f"{configuration.url_base_path}/login")

@app.route(f"{configuration.url_base_path}/static/<string:folder>/<string:filename>")
async def get_static_file(folder: str, filename: str):
    authenticated = not configuration.require_login or await current_user.is_authenticated
    authorized = not configuration.require_login or (authenticated and int(current_user.auth_id) in configuration.authorized_discord_users)
    if folder == "css":
        if filename not in ("guest_dashboard.css", "login.css"):
            if not authenticated:
                return abort(401)
            if not authorized:
                return abort(403)
        if filename == "guest_dashboard.css" and (not configuration.public_dashboard or not configuration.require_login):
            return abort(404)
        if filename == "login.css" and not configuration.require_login:
            return abort(404)
        path = safe_join("static/css/", filename)
    elif folder == "images":
        path = safe_join("static/images/", filename)
    elif folder == "js":
        if filename not in ("guest_dashboard.js", "login.js"):
            if not authenticated:
                return abort(401)
            if not authorized:
                return abort(403)
        if filename == "guest_dashboard.js" and (not configuration.public_dashboard or not configuration.require_login):
            return abort(404)
        if filename == "login.js" and not configuration.require_login:
            return abort(404)
        path = safe_join("static/js/", filename)
    else:
        return abort(404)
    if path is not None and await aioos.path.exists(path):
        return await send_file(path)
    return abort(404)

@app.route(f"{configuration.url_base_path}/mods/<string:filename>")
async def get_mod_file(filename: str):
    authenticated = not configuration.require_login or await current_user.is_authenticated
    authorized = not configuration.require_login or (authenticated and int(current_user.auth_id) in configuration.authorized_discord_users)
    if not configuration.public_dashboard:
        if not authenticated:
            return abort(401)
        if not authorized:
            return abort(403)
    path = safe_join("Resources/Client/", filename)
    if path is None or (path is not None and not await aioos.path.exists(path)):
        if not authenticated:
            return abort(404)
        path = safe_join("Resources/Client.disabled/", filename)

    chunk_size = 10 * 1024 * 1024 # 10 MB

    if path is not None and await aioos.path.exists(path):
        range_header = request.headers.get("Range", None)
        file_size = await aioos.path.getsize(path)

        # Stream the partial file to the client, if requested
        if range_header:
            # Parse the range header
            range_value = range_header.strip().lower().replace("bytes=", "")
            start_str, end_str = range_value.split("-")
            try:
                start = int(start_str)
                end = int(end_str) if end_str else file_size - 1
            except ValueError:
                return abort(400)
            if start >= file_size or end >= file_size:
                return Response(status=416)

            requested_chunk_size = end - start + 1

            async def partial_gen():
                async with aiofiles.open(path, mode="rb") as f:
                    await f.seek(start)
                    remaining = requested_chunk_size
                    while remaining > 0:
                        read_size = min(chunk_size, remaining)
                        chunk = await f.read(read_size)
                        if not chunk:
                            break
                        yield chunk
                        remaining -= len(chunk)

            response = Response(partial_gen(), status=206, headers={
                "Content-Type": "application/zip",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(chunk_size),
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
            })
            response.timeout = 300 # Timeout sending the file after 5 minutes
            return response

        # Stream the whole file to the client
        async def generate():
            async with aiofiles.open(path, 'rb') as f:
                while chunk := await f.read(chunk_size):
                    yield chunk
        response = Response(generate(), headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/zip",
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
        })
        response.timeout = 300 # Timeout sending the file after 5 minutes
        return response
    return abort(404)

# -- Mod Upload --

def check_zip_sync(path) -> bool:
    """
    Check whether a zip file is valid.
    """
    valid = True
    try:
        with zipfile.ZipFile(path) as zip:
            check = zip.testzip()
        if check is not None:
            valid = False
    except zipfile.BadZipFile:
        valid = False
    return valid

def detect_zip_levels(path) -> str | None:
    """
    Search for level information files, and returns the path if found.
    """
    filename = None
    with zipfile.ZipFile(path) as zip:
        filelist = zip.filelist
    for file in filelist:
        # Search for map info files (levelname/info.json is the more modern format, and levelname/levelname.mis is old but still used)
        if file.filename.startswith("levels/") and (file.filename.endswith("/info.json") or file.filename.endswith(".mis")):
            filename = "/" + file.filename # Add a '/' to the beginning to match the correct format
    return filename

@app.route(f"{configuration.url_base_path}/upload", methods=["POST"])
@authorization_required(["modify_mods"])
async def upload():
    content_range = request.headers.get("Content-Range")
    form = await request.form
    files = await request.files
    chunk: FileStorage | None = files.get("chunk")
    filename: str | None = form.get("filename")
    if chunk is None:
        chunk: str | None = form.get("chunk")
        if chunk != "false":
            return abort(400)
    if filename is None or content_range is None:
        return abort(400)

    # Extract byte range
    match = re.match(r"bytes (\d+)-(\d+)/(\d+)", content_range)
    if not match:
        return abort(400)
    start, end, total = map(int, match.groups())

    filename = secure_filename(filename + ".zip")

    async with temp_files_lock:
        # Check if chunk is a request to abort the upload
        if chunk == "false":
            if filename in temp_files:
                if temp_files[filename].user != current_user.auth_id:
                    return abort(403)
                if temp_files[filename].total_bytes == total:
                    path = safe_join("Resources/Client.temp/", filename + ".part")
                    await aioos.remove(path)
                    del temp_files[filename]
                    return Response("Aborted upload", 200)
            return abort(400)

        # Validate request
        if chunk.content_type != "application/octet-stream":
            return abort(415)
        if not filename.endswith(".zip") or len(filename) <= 4 or len(filename) > 24: # Make sure filename is long enough to contain a character and '.zip'
            return abort(400)
        if filename in await aioos.listdir("Resources/Client/") or filename in await aioos.listdir("Resources/Client.disabled/"):
            return abort(409)

        if total / (1024 * 1024 * 1024) >= 1: # Max 1 GiB
            return abort(413)

        temp_path = safe_join("Resources/Client.temp/", filename + ".part")
        if temp_path is None:
            return abort(400)

        if start == 0:
            if filename in temp_files:
                return abort(409)

            temp_files[filename] = TempFile(total_bytes=total, user=current_user.auth_id)
        elif filename in temp_files and temp_files[filename].user != current_user.auth_id:
            return abort(403)
        elif filename not in temp_files or temp_files[filename].total_bytes != total or temp_files[filename].expected_next_byte != start or end >= total:
            return abort(400)
        elif filename in temp_files and temp_files[filename].complete:
            return abort(409)

        temp_files[filename].last_write = datetime.datetime.now()

        to_write: bytes = chunk.read()
        if len(to_write) != end - start + 1:
            return abort (400)

        temp_files[filename].hasher.update(to_write)
        async with aiofiles.open(temp_path, "ab") as f:
            await f.seek(start)
            await f.write(to_write)
            current_pos = await f.tell()
        temp_files[filename].expected_next_byte = current_pos

        # Check if the file is a zip file
        if start == 0:
            async with aiofiles.open(temp_path, "rb") as f:
                header = await f.read(4)
                if not header.startswith(b'\x50\x4B\x03\x04'):
                    await aioos.remove(temp_path)
                    return abort(415)

        if end + 1 == total:
            mod_hash = temp_files[filename].hasher.hexdigest()
            temp_files[filename].complete = True
            # Check if the zip file is valid
            valid = await asyncio.to_thread(check_zip_sync, temp_path)
            if not valid:
                await aioos.remove(temp_path)
                return abort(415)

            # Check if file is malicious with VirusTotal
            if configuration.virustotal_scanning:
                if VT_KEY is None:
                    raise KeyError("The VT_KEY environment variable is required for VirusTotal scanning.")
                async with vt.Client(VT_KEY) as client: # Regular 'with vt.Client()' doesn't work for some reason so we use 'async with vt.Client()'
                    try:
                        vt_file = await client.get_object_async(f"/files/{mod_hash}")
                        if vt_file.error is not None:
                            raise vt.error.APIError("NotFoundError", "Analysis stats not found.") # Manually raise a NotFoundError to trigger a scan if there is an error
                        analysis_stats = vt_file.last_analysis_stats
                        total = analysis_stats["malicious"] + analysis_stats["suspicious"] + analysis_stats["undetected"] + analysis_stats["harmless"]
                        bad = analysis_stats["malicious"] + analysis_stats["suspicious"]
                        if total == 0 or bad / total > 0.25:
                            await aioos.remove(temp_path)
                            del temp_files[filename]
                            return abort(422) # Refuse to upload the file if the file is too suspicious
                    except vt.error.APIError as error:
                        if error.code == "NotFoundError":
                            if await aioos.path.getsize(temp_path) >= 650 * 1000 * 1000: # Don't allow to upload files over 650MB to VirusTotal
                                return abort(413)
                            with open(temp_path, "rb") as file:
                                try:
                                    await client.scan_file_async(file, wait_for_completion=True)
                                    vt_file = await client.get_object_async(f"/files/{mod_hash}")
                                except vt.error.APIError as error:
                                    await aioos.remove(temp_path)
                                    del temp_files[filename]
                                    raise error

                                if vt_file.error is not None:
                                    await aioos.remove(temp_path)
                                    del temp_files[filename]
                                    return abort(500)

                                analysis_stats = vt_file.last_analysis_stats
                                total = analysis_stats["malicious"] + analysis_stats["suspicious"] + analysis_stats["undetected"] + analysis_stats["harmless"]
                                bad = analysis_stats["malicious"] + analysis_stats["suspicious"]
                                if total == 0 or bad / total > 0.25:
                                    await aioos.remove(temp_path)
                                    del temp_files[filename]
                                    return abort(422) # Refuse to upload the file if the file is too suspicious
                        else:
                            await aioos.remove(temp_path)
                            del temp_files[filename]
                            raise error

            # Add the level path to the configuration, if enabled
            if configuration.detect_mod_maps:
                level = await asyncio.to_thread(detect_zip_levels, temp_path)
                if level is not None:
                    async with state_lock:
                        old_data = snapshot_server_data()
                        if await server_data.persistent_data.add_level_hash(mod_hash, level) and configuration.persist_data:
                            await server_data.persistent_data.dump_and_write() # Write the changes to disk
                        await send_changed_data(old_data) # Update levels over websocket

            final_path = safe_join("Resources/Client/", filename)
            shutil.move(temp_path, final_path)
            del temp_files[filename]
            await run_command("reloadmods")
            return Response(filename, 201)

        return Response("Chunk stored", 206)

# -- Data Websocket --

async def process_websocket_request(ws_request: str) -> dict[str] | Literal[True] | None:
    ws_request = json.loads(ws_request)
    if "type" not in ws_request:
        return None
    match ws_request["type"]:
        case "request":
            if "request" not in ws_request:
                return None
            match ws_request["request"]:
                case "all":
                    return server_data.model_dump()
                case "connected":
                    return {"connected": server_data.connected}
                case "error":
                    return {"error": server_data.error}
                case "version":
                    return {"version": server_data.version}
                case "lua_version":
                    return {"lua_version": server_data.lua_version}
                case "port":
                    return {"port": server_data.port}
                case "max_clients":
                    return {"max_clients": server_data.max_clients}
                case "mods":
                    return {"mods": server_data.mods}
                case "players":
                    return {"players": server_data.players}
                case "logs":
                    return {"logs": server_data.logs}
                case "mod_list":
                    mods = None
                    async with aiofiles.open("Resources/Client/mods.json") as file:
                        mods: dict[str, dict[str, bool | str | int]] | None = json.loads(await file.read())
                    if mods is not None:
                        for _, mod in mods.items():
                            mod.pop("hash")
                            mod.pop("lastwrite")
                            mod.pop("protected")
                            mod["enabled"] = True

                        mods_disabled = None
                        async with aiofiles.open("Resources/Client.disabled/mods.json") as file:
                            mods_disabled: dict[str, dict[str, bool | str | int]] | None = json.loads(await file.read())
                        if mods_disabled is not None:
                            for _, mod in mods_disabled.items():
                                mod.pop("hash")
                                mod.pop("lastwrite")
                                mod.pop("protected")
                                mod["enabled"] = False
                            mods.update(mods_disabled)
                        return {"mod_list": mods}
                case "levels":
                    return {"levels": server_data.levels}
                case "update":
                    if not user_has_permissions(current_user, ["configure"]):
                        return None
                    async with release_cache.lock:
                        if release_cache.last_cache is None or release_cache.last_cache + datetime.timedelta(minutes=2) < datetime.datetime.now():
                            updated = await update_release_cache()
                            if not updated:
                                return None
                        release = release_cache.model_dump()
                        release["system_architecture"] = architecture
                    return {"update": release}
                case "permissions":
                    if not configuration.require_login:
                        return {"permissions": True}
                    return {"permissions": configuration.authorized_discord_users.get(int(current_user.auth_id)).permissions}
                case "beampaint_installed":
                    return {"beampaint_installed": server_data.beampaint_installed}
        case "command":
            if "command" not in ws_request:
                return None
            if not user_has_permissions(current_user, ["manage_server"]):
                return None
            match ws_request["command"]:
                case "restart":
                    if server_executable_lock.locked():
                        return {"action": "restart", "success": False}
                    if server_data.process is not None and server_data.process.returncode is None:
                        server_data.process.terminate()
                    await start_server()
                    return {"action": "restart"}
                case "stop":
                    if server_data.process is not None:
                        server_data.process.terminate()
                        async with state_lock:
                            reset_server_data()
                        return {"action": "stop"}
                    return {"action": "stop", "success": False}
                case "kick":
                    if "player" not in ws_request or "reason" not in ws_request:
                        return None
                    if server_data.process is not None:
                        await run_command(f"kick {ws_request["player"]} {ws_request["reason"]}")
                        return {"action": "kick"}
                case "say":
                    if "message" not in ws_request:
                        return None
                    if server_data.process is not None:
                        await run_command(f"say {ws_request["message"]}")
                        return {"action": "say"}
                case "reloadmods":
                    if server_data.process is not None:
                        await run_command("reloadmods")
                        return {"action": "reloadmods"}
        case "enable":
            if "enable" not in ws_request:
                return None
            if not user_has_permissions(current_user, ["modify_mods"]):
                return None
            path = safe_join("Resources/Client.disabled/", ws_request["enable"])
            if path is None or not await aioos.path.exists(path):
                return {"action": "enable", "success": False}
            shutil.move(path, "Resources/Client/")

            # Remove enabled mod information from disabled json file
            mods_disabled = None
            async with aiofiles.open("Resources/Client.disabled/mods.json") as file:
                mods_disabled: dict[str, dict[str, bool | str | int]] | None = json.loads(await file.read())
            if mods_disabled is not None and ws_request["enable"] in mods_disabled:
                # Add enabled mods information to enabled json file to prevent rehashing for better performance
                mods = None
                async with aiofiles.open("Resources/Client/mods.json") as file:
                    mods: dict[str, dict[str, bool | str | int]] | None = json.loads(await file.read())
                if mods is not None and ws_request["enable"] not in mods:
                    mods[ws_request["enable"]] = mods_disabled[ws_request["enable"]]
                elif mods is None:
                    mods = {ws_request["enable"]: mods_disabled[ws_request["enable"]]}
                to_write = json.dumps(mods)
                async with aiofiles.open("Resources/Client/mods.json", "w") as file:
                    await file.write(to_write)

                # Continue removing enabled mod information from disabled json file
                del mods_disabled[ws_request["enable"]]
                if len(mods_disabled) == 0:
                    mods_disabled = None
                to_write = json.dumps(mods_disabled)
                async with aiofiles.open("Resources/Client.disabled/mods.json", "w") as file:
                    await file.write(to_write)

                # Add the level path to the configuration, if enabled
                if configuration.detect_mod_maps:
                    level = await asyncio.to_thread(detect_zip_levels, safe_join("Resources/Client/", ws_request["enable"]))
                    if level is not None:
                        async with state_lock:
                            old_data = snapshot_server_data()
                            if await server_data.persistent_data.add_level_hash(mods[ws_request["enable"]]["hash"], level) and configuration.persist_data:
                                await server_data.persistent_data.dump_and_write() # Write the changes to disk and update over the websocket
                            await send_changed_data(old_data)

            # Reload mods to update mods list
            await run_command("reloadmods")

            return {"action": "enable"}
        case "disable":
            if "disable" not in ws_request:
                return None
            if not user_has_permissions(current_user, ["modify_mods"]):
                return None
            path = safe_join("Resources/Client/", ws_request["disable"])
            if path is None or not await aioos.path.exists(path):
                return {"action": "disable", "success": False}
            shutil.move(path, "Resources/Client.disabled/")

            # Add disabled mod information to disabled json file
            async with aiofiles.open("Resources/Client/mods.json") as file:
                mods: dict[str, dict[str, bool | str | int]] | None = json.loads(await file.read())
            mod_info = mods[ws_request["disable"]]
            mods_disabled = None
            async with aiofiles.open("Resources/Client.disabled/mods.json") as file:
                mods_disabled: dict[str, dict[str]] | None = json.loads(await file.read())
            if mods_disabled is None:
                mods_disabled = {ws_request["disable"]: mod_info}
            else:
                mods_disabled[ws_request["disable"]] = mod_info
            to_write = json.dumps(mods_disabled, sort_keys=True)
            async with aiofiles.open("Resources/Client.disabled/mods.json", "w") as file:
                await file.write(to_write)

            # Reload mods to update mods list
            await run_command("reloadmods")
            # Remove the mod hash from any level filepaths, if applicable
            if configuration.detect_mod_maps:
                async with state_lock:
                    old_data = snapshot_server_data()
                    if await server_data.persistent_data.remove_level_hash(mods[ws_request["disable"]]["hash"]) and configuration.persist_data:
                        await server_data.persistent_data.dump_and_write()
                    await send_changed_data(old_data)

            return {"action": "disable"}
        case "delete":
            if "delete" not in ws_request:
                return None
            if not user_has_permissions(current_user, ["modify_mods"]):
                return None
            disabled = False
            path = safe_join("Resources/Client/", ws_request["delete"])
            if path is None or not await aioos.path.exists(path):
                path = safe_join("Resources/Client.disabled/", ws_request["delete"])
                disabled = True
            if path is None or not await aioos.path.exists(path):
                return {"action": "delete", "success": False}
            await aioos.remove(path)

            # Remove deleted mod information from disabled json file, if applicable
            if disabled:
                mods_disabled = None
                async with aiofiles.open("Resources/Client.disabled/mods.json") as file:
                    mods_disabled: dict[str, dict[str, bool | str | int]] | None = json.loads(await file.read())
                if mods_disabled is not None and ws_request["delete"] in mods_disabled:
                    del mods_disabled[ws_request["delete"]]
                to_write = json.dumps(mods_disabled)
                async with aiofiles.open("Resources/Client.disabled/mods.json", "w") as file:
                    await file.write(to_write)
            else:
                async with aiofiles.open("Resources/Client/mods.json") as file:
                    mods: dict[str, dict[str, bool | str | int]] | None = json.loads(await file.read())
                if mods is not None and ws_request["delete"] in mods:
                    mod_hash = mods[ws_request["delete"]]["hash"]
                    # Reload mods to update mods list if deleted mod was enabled
                    await run_command("reloadmods")
                    # Remove the mod hash from any level filepaths, if applicable
                    if configuration.detect_mod_maps:
                        async with state_lock:
                            old_data = snapshot_server_data()
                            if await server_data.persistent_data.remove_level_hash(mod_hash) and configuration.persist_data:
                                await server_data.persistent_data.dump_and_write()
                            await send_changed_data(old_data)
            return {"action": "delete"}
        case "get":
            if "setting" not in ws_request:
                return None
            if ws_request["setting"] == "all":
                return server_settings.model_dump()
            if hasattr(server_settings, ws_request["setting"]):
                return {ws_request["setting"]: getattr(server_settings, ws_request["setting"]), "type": "settings"}
            return {"action": "get", "success": False}
        case "set":
            if "setting" not in ws_request or "value" not in ws_request:
                return None
            if not user_has_permissions(current_user, ["modify_settings"]):
                return None
            if hasattr(server_settings, ws_request["setting"]):
                expected_value = getattr(server_settings, ws_request["setting"])
                if not isinstance(ws_request["value"], type(expected_value)):
                    return None
                if server_data.process is not None:
                    await run_command(f"settings set General {ws_request["setting"]} {json.dumps(ws_request["value"])}")

                # Save the setting change to disk so it is preserved after restart
                if configuration.preserve_setting_changes and await aioos.path.exists("ServerConfig.toml"):
                    async with aiofiles.open("ServerConfig.toml") as file:
                        toml_str = await file.read()
                    toml = tomlkit.parse(toml_str)
                    toml["General"][ws_request["setting"]] = ws_request["value"]
                    to_write = tomlkit.dumps(toml)
                    async with aiofiles.open("ServerConfig.toml", "w") as file:
                        await file.write(to_write)

                return {"action": ws_request["setting"], "type": "settings"}
            return {"action": "set", "success": False}
        case "clear":
            if "data" not in ws_request:
                return None
            match ws_request["data"]:
                case "logs":
                    if not user_has_permissions(current_user, ["clear_logs"]):
                        return None
                    async with state_lock:
                        old_data = snapshot_server_data()
                        server_data.persistent_data.logs.clear()
                        if configuration.persist_data:
                            await server_data.persistent_data.dump_and_write()
                        await send_changed_data(old_data)
                    return {"action": "clear"}
            return {"action": "clear", "success": False}
        case "update":
            if "download_url" not in ws_request:
                return None
            if not user_has_permissions(current_user, ["configure"]):
                return None
            async with release_cache.lock:
                if (release_cache.last_cache is None or release_cache.last_cache + datetime.timedelta(minutes=2) < datetime.datetime.now()):
                    updated = await update_release_cache()
                    if not updated:
                        return None
            for file in release_cache.files:
                if file.download_url == ws_request["download_url"]:
                    filepath = configuration.beammp_executable_path + ".temp"
                    if await aioos.path.exists(filepath): # Make sure the temporary update file doesn't already exist
                        return {"action": "update", "success": False}

                    async with aiohttp.ClientSession() as session:
                        async with session.get(file.download_url) as response:
                            if response.status < 200 or response.status >= 300:
                                return {"action": "update", "success": False}
                            async with aiofiles.open(filepath, "wb") as file:
                                async for chunk in response.content.iter_chunked(10 * 1024 * 1024): # Download the updated server in chunks of 10 MB
                                    await file.write(chunk)
                    async with server_executable_lock:
                        if server_data.process is not None and server_data.process.returncode is None:
                            server_data.process.terminate()
                        if await aioos.path.exists(configuration.beammp_executable_path):
                            try:
                                await aioos.remove(configuration.beammp_executable_path)
                            except (PermissionError, OSError):
                                logger.exception("Failed to delete server executable")
                                await aioos.remove(filepath)
                                return {"action": "update", "success": False}

                        await aioos.rename(filepath, configuration.beammp_executable_path)
                        st = await aioos.stat(configuration.beammp_executable_path)
                        await asyncio.to_thread(os.chmod, configuration.beammp_executable_path, st.st_mode | stat.S_IEXEC) # Set the file as executable for the current user

                        await start_server()
                    return {"action": "update"}
            return {"action": "update", "success": False}
        case "beampaint":
            if "action" not in ws_request:
                return None
            if not user_has_permissions(current_user, ["configure"]):
                return None

            match ws_request["action"]:
                case "install":
                    if await aioos.path.exists("Resources/Server/BeamPaintUpdater/"):
                        return {"action": "beampaint", "type": "install", "success": False}

                    await aioos.mkdir("Resources/Server/BeamPaintUpdater")
                    filepath = "Resources/Server/BeamPaintUpdater/main.lua.temp"
                    if await aioos.path.exists(filepath): # Make sure the temporary beampaint file doesn't already exist
                        return {"action": "beampaint", "type": "install", "success": False}

                    async with aiohttp.ClientSession() as session:
                        async with session.get(BEAMPAINT_MAIN_LUA) as response:
                            if response.status < 200 or response.status >= 300:
                                return {"action": "beampaint", "type": "install", "success": False}
                            async with aiofiles.open(filepath, "wb") as file:
                                await file.write(await response.content.read())
                    await aioos.rename(filepath, "Resources/Server/BeamPaintUpdater/main.lua")

                    async with state_lock:
                        old_data = snapshot_server_data()
                        server_data.beampaint_installed = True
                        await send_changed_data(old_data)
                    return {"action": "beampaint", "type": "install"}
                case "uninstall":
                    try:
                        for folder in ("Resources/Server/BeamPaintUpdater/", "Resources/Server/BeamPaintServerPlugin/"):
                            if await aioos.path.exists(folder):
                                for file in await aioos.listdir(folder):
                                    await aioos.remove(folder + file)
                                await aioos.rmdir(folder)
                        if await aioos.path.exists("Resources/Client/BeamPaint.zip"):
                            await aioos.remove("Resources/Client/BeamPaint.zip")
                    except (PermissionError, OSError):
                        logger.exception("Failed to delete all BeamPaint files!")
                        return {"action": "beampaint", "type": "uninstall", "success": False}
                    await run_command("reloadmods")
                    async with state_lock:
                        old_data = snapshot_server_data()
                        server_data.beampaint_installed = False
                        await send_changed_data(old_data)
                    return {"action": "beampaint", "type": "uninstall"}
        case "ping":
            return True
    return None

async def receive() -> None:
    """
    Receive and process data from a websocket.
    """
    while True:
        ws_request = await websocket.receive()
        result = await process_websocket_request(ws_request)
        if result is None:
            result = {"success": False}
        elif result is True:
            continue # Don't send a response back to the client for pings
        elif "success" not in result:
            result["success"] = True
        await websocket.send(json.dumps(result))

@app.websocket(f"{configuration.url_base_path}/ws")
@authorization_required()
async def websocket_connect():
    try:
        task = asyncio.ensure_future(receive())
        websockets.append(task)
        permissions = {"permissions": configuration.authorized_discord_users.get(int(current_user.auth_id)).permissions} if configuration.require_login else {"permissions": True}
        await websocket.send(json.dumps(permissions))
        data = server_data.model_dump_json()
        await websocket.send(data)
        data = server_settings.model_dump()
        data["type"] = "settings"
        await websocket.send(json.dumps(data))
        async for data in broker.subscribe():
            if data is None:
                break
            await websocket.send(data)
    finally:
        websockets.remove(task)
        if not task.done():
            task.cancel()
        await task

# Redirect to login page if unauthorized
@app.errorhandler(Unauthorized)
async def redirect_to_login(*_):
    return redirect(f"{configuration.url_base_path}/login")

async def process_new_lines(new_lines: list[str]) -> None:
    async with server_data.persistent_data.lock:
        for line in new_lines:
            data = line.split(" ")
            if len(data) >= 3 and data[2][0] == "[" and data[2][-1] == "]":
                if data[2] == "[INFO]":
                    if "ALL SYSTEMS STARTED SUCCESSFULLY, EVERYTHING IS OKAY" in line:
                        server_data.connected = True
                    elif "BeamMP Server v" in line:
                        server_data.version = line.split(" ")[-1]
                    elif "Lua v" in line:
                        server_data.lua_version = line.split()[-1]
                    elif "Vehicle data network online on port " in line:
                        for i, word in enumerate(data):
                            if len(data) > i + 1 and data[i + 1].lower() == "clients":
                                try:
                                    int(word)
                                except ValueError:
                                    continue
                                else:
                                    server_data.max_clients = int(word)
                            elif i >= 1 and data[i - 1].lower() == "port":
                                server_data.port = int(word)

                        server_data.persistent_data.logs.append({"message": "Server Started", "type": "start", "timestamp": " ".join(data[0:2])})

                        # Get loaded settings
                        if server_data.process is not None:
                            await run_command("settings list")
                    elif "Loaded " in line and " Mods" in line:
                        mods = data[-2]
                        try:
                            int(mods)
                        except ValueError:
                            continue
                        else:
                            server_data.mods = int(mods)
                    elif "Assigned ID " in line and " to " in line:
                        for i, word in enumerate(data):
                            if i >= 1 and data[i - 1] == "ID":
                                try:
                                    int(word)
                                except ValueError:
                                    continue
                                else:
                                    server_data.players[word] = data[-1]
                                    server_data.persistent_data.logs.append({"player": data[-1], "type": "join", "timestamp": " ".join(data[0:2])})
                                    break
                    elif " is now synced!" in line:
                        for i, word in enumerate(data):
                            if len(data) > i - 1 and data[i + 1] == "is":
                                server_data.persistent_data.logs.append({"player": data[i], "type": "sync", "timestamp": " ".join(data[0:2])})
                                break
                    elif " Connection Terminated" in line:
                        for i, word in enumerate(data):
                            if len(data) > i + 1 and data[i + 1] == "Connection":
                                for key in server_data.players:
                                    name = server_data.players[key]
                                    if name == word:
                                        del server_data.players[key]
                                        break
                                server_data.persistent_data.logs.append({"player": word, "type": "leave", "timestamp": " ".join(data[0:2])})
                                break
                elif data[2] == "[ERROR]":
                    if "bind() failed: Address already in use" in line:
                        server_data.error = True
                elif data[2] == "[CHAT]":
                    if data[3] == "<Server>":
                        sender = data[3].removeprefix("<").removesuffix(">")
                        receiver = data[5].split(")")[0]
                        receiver = receiver.replace('"', "'")
                        message = data[5].split(")")[-1] + " " + " ".join(data[6:])
                    else:
                        sender = data[4].removeprefix("<").removesuffix(">")
                        receiver = "everyone"
                        message = " ".join(data[5:])
                    server_data.persistent_data.logs.append({"type": "message", "sender": sender, "receiver": receiver, "message": message, "timestamp": " ".join(data[0:2])})
                elif data[2] == "[LUA]" or data[2] == "[LUA" and data[3] == "WARN]":
                    pass # Server-side mods can trigger these log types
                else:
                    logger.warning(f"Invalid log type {data[2]}")
            elif "::" in data[0]:
                if "General::" in data[0]:
                    setting = data[0].split("::")[-1]
                    if not hasattr(server_settings, setting):
                        continue
                    value = line.split(" = ")[-1] if " = " in line else line.split(" := ")[-1]
                    server_settings.model_construct()
                    if value in ("true", "false"):
                        value = value == "true"
                    else:
                        with contextlib.suppress(ValueError):
                            value = int(value)
                    setattr(server_settings, setting, value)
                elif "Misc::" in data[0]:
                    continue
                else:
                    logger.warning(f"Invalid setting type {data[0]}")
            elif data[0] == ">":
                continue
            elif data[0] == "Mods" and data[1] == "reloaded.":
                mods = await aioos.listdir("Resources/Client/")
                mod_count = 0
                for mod in mods:
                    if not mod.endswith(".json"):
                        mod_count += 1

                server_data.mods = mod_count
            elif (data[0] == "Kicked" and data[1] == "player") or "Error: No player with name matching" in line:
                continue
            else:
                logger.warning("Invalid line format!")
    return

async def monitor_logs() -> None:
    """
    Monitor the Server.log file and process any new lines.
    """
    global log_file_position
    while True:
        await asyncio.sleep(0.5)
        if server_data.process is not None and server_data.process.returncode is None:
            try:
                async with aiofiles.open("Server.log") as file:
                    await file.seek(log_file_position)
                    output = await file.read()
                    log_file_position = await file.tell()
            except OSError as e:
                logger.exception("Could not open and read from Server.log")
                raise e

            async with state_lock:
                # Save old data and settings to compare with afterwards
                old_data = snapshot_server_data()
                old_settings = snapshot_settings()

                new_lines = output.splitlines()
                if len(new_lines) > 0:
                    await process_new_lines(new_lines)

                    await server_data.persistent_data.trim_logs(configuration.maximum_log_entries)
                    if configuration.persist_data:
                        await server_data.persistent_data.dump_and_write()

                    await send_changed_data(old_data, old_settings)

                    logger.debug(f"Processed {len(new_lines)} new lines")
        elif server_data.process is not None:
            logger.error("BeamMP server exited with returncode %s", server_data.process.returncode)
            old_data = snapshot_server_data()
            async with state_lock:
                reset_server_data()
            server_data.error = True
            await send_changed_data(old_data)

async def monitor_temp_files() -> None:
    """
    Delete temporary files if it has been over a minute since the last write.
    """
    while True:
        await asyncio.sleep(1)
        async with temp_files_lock:
            expired_items = []
            for filename, data in temp_files.items():
                if data.last_write is not None and not data.complete and data.last_write + datetime.timedelta(minutes=1) < datetime.datetime.now():
                    path = safe_join("Resources/Client.temp/", filename + ".part")
                    if await aioos.path.exists(path):
                        await aioos.remove(path)
                    expired_items.append(filename)
            for filename in expired_items:
                del temp_files[filename]

@app.before_serving
async def startup():
    # Make sure all necessary folders and files exist and clear any temporary files
    if "Resources" not in await aioos.listdir():
        await aioos.mkdir("Resources")
    folders = await aioos.listdir("Resources/")
    if "Client" not in folders:
        await aioos.mkdir("Resources/Client")
    if "Client.disabled" not in folders:
        await aioos.mkdir("Resources/Client.disabled")
    if "Server" not in folders:
        await aioos.mkdir("Resources/Server")
    if "Client.temp" not in folders:
        await aioos.mkdir("Resources/Client.temp")
    if len(await aioos.listdir("Resources/Client.temp")) != 0:
        temp_files = await aioos.listdir("Resources/Client.temp")
        for file in temp_files:
            await aioos.remove(os.path.join("Resources/Client.temp/", file))
    if "mods.json" not in await aioos.listdir("Resources/Client/"):
        async with aiofiles.open("Resources/Client/mods.json", "w") as file:
            await file.write(json.dumps(None))
    if "mods.json" not in await aioos.listdir("Resources/Client.disabled/"):
        async with aiofiles.open("Resources/Client.disabled/mods.json", "w") as file:
            await file.write(json.dumps(None))

    # Start BeamMP Server and start monitoring logs
    await start_server()
    app.tasks = []
    app.tasks.append(asyncio.create_task(monitor_logs()))
    app.tasks.append(asyncio.create_task(monitor_temp_files()))

@app.after_serving
async def shutdown():
    if hasattr(app, "tasks"):
        for task in app.tasks:
            task.cancel()
    if server_data.process is not None and server_data.process.returncode is None:
        server_data.process.terminate()

# Close websockets upon shutdown
def close_sockets(*_):
    asyncio.create_task(broker.event(None))

signal.signal(signal.SIGINT, close_sockets)
signal.signal(signal.SIGTERM, close_sockets)

# By @peterservices
