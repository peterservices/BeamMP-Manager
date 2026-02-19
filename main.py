import asyncio
import contextlib
import copy
import datetime
import hashlib
import json
import os
import re
import shutil
import signal
import typing
import zipfile
from collections.abc import AsyncGenerator
from secrets import token_urlsafe
from typing import Any

import aiofiles
import aiofiles.os as aioos
import discordoauth2
import tomlkit
import vt
from dotenv import find_dotenv, load_dotenv, set_key
from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from quart import (
    Quart,
    Response,
    abort,
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

DOTENV_PATH = find_dotenv()
load_dotenv(dotenv_path=DOTENV_PATH)

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
if CLIENT_ID is None or CLIENT_SECRET is None:
    raise KeyError("Both the CLIENT_ID and CLIENT_SECRET envirnoment variables are required for Discord login.")

SECRET_KEY = os.getenv("SECRET_KEY")
if SECRET_KEY is None:
    SECRET_KEY = token_urlsafe() # Generate a new SECRET_KEY
    if DOTENV_PATH != "":
        set_key(DOTENV_PATH, "SECRET_KEY", SECRET_KEY) # Save the SECRET_KEY to preserve sessions across restarts

VT_KEY = os.getenv("VT_KEY")

app = Quart(__name__)
app.secret_key = SECRET_KEY

QuartAuth(app, duration=30 * 24 * 60 * 60)

class LocalConfiguration(BaseModel):
    beammp_executable_path: str = "BeamMP-Server"
    url_base_path: str = "/beammp"
    discord_oauth2_redirect_url: str = ""
    virustotal_scanning: bool = True
    preserve_settings_changes: bool = True
    detect_mod_maps: bool = True
    public_dashboard: bool = True
    levels: list[str] = [
        "/levels/automation_test_track/info.json",
        "/levels/cliff/info.json",
        "/levels/derby/info.json",
        "/levels/driver_training/info.json",
        "/levels/east_coast_usa/info.json",
        "/levels/gridmap_v2/info.json",
        "/levels/hirochi_raceway/info.json",
        "/levels/industrial/info.json",
        "/levels/italy/info.json",
        "/levels/johnson_valley/info.json",
        "/levels/jungle_rock_island/info.json",
        "/levels/small_island/info.json",
        "/levels/smallgrid/info.json",
        "/levels/utah/info.json",
        "/levels/west_coast_usa/info.json",
    ]
    authorized_users: list[int] = []

class ServerData(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    process: asyncio.subprocess.Process | None = Field(None, exclude=True)
    connected: bool = False
    error: bool = False
    version: str | None = None
    lua_version: str | None = None
    port: int | None = None
    max_clients: int | None = None
    mods: int = 0
    players: dict[str, str] = {}
    player_logs: list[dict[str, str]] = []
    chat_logs: list[dict[str, str | list]] = []

class ServerSettings(BaseModel):
    InformationPacket: bool | None = None
    AllowGuests: bool | None = None
    Description: str | None = None
    Tags: str | None = None
    MaxCars: int | None = None
    MaxPlayers: int | None = None
    Name: str | None = None
    Map: str | None = None
    Private: bool | None = None
    IP: str | None = None
    Port: int | None = None
    LogChat: bool | None = None
    Debug: bool | None = None
    ResourceFolder: str | None = None

class TempFile(BaseModel):
    def _validate_hash_obj(obj: object): # Check if the object has the attributes of a HASH object, because there is no HASH type to compare against
        if hasattr(obj, "update") and hasattr(obj, "digest") and hasattr(obj, "hexdigest") and hasattr(obj, "copy"):
            return obj
        raise ValueError("Must be a HASH object!")

    total_bytes: int
    user: str
    hasher: typing.Annotated[object, AfterValidator(_validate_hash_obj)] = hashlib.sha256()
    complete: bool = False
    last_write: datetime.datetime | None = None

class Broker:
    def __init__(self) -> None:
        self.connections: set[asyncio.Queue] = set()

    async def event(self, data: dict[str, Any] | None) -> None:
        if data is not None: # If data is None, it is a shutdown request and shouldn't be serialized
            data = json.dumps(data)

        # Send event data
        for connection in self.connections:
            await connection.put(data)

    async def subscribe(self) -> AsyncGenerator[str, None]:
        connection = asyncio.Queue()
        self.connections.add(connection)
        try:
            while True:
                yield await connection.get()
        finally:
            self.connections.remove(connection)

configuration = LocalConfiguration()
if not os.path.exists("config.json"):
    to_write = configuration.model_dump_json(indent=5)
    with open("config.json", "x") as file:
        file.write(to_write)
else:
    with open("config.json") as file:
        config_str = file.read()
    configuration = LocalConfiguration.model_validate_json(config_str)
    if configuration and os.path.exists(configuration.beammp_executable_path):
        configuration.beammp_executable_path = os.path.abspath(configuration.beammp_executable_path)

    # Save any new changes to disk
    if configuration.model_dump_json() != config_str:
        to_write = configuration.model_dump_json(indent=5)
        with open("config.json", "w") as file:
            file.write(to_write)

oauth_client = discordoauth2.AsyncClient(id=CLIENT_ID, secret=CLIENT_SECRET, redirect=configuration.discord_oauth2_redirect_url, bot_token="")

server_data = ServerData(process=None, connected=False, error=False, version=None, lua_version=None, port=None, max_clients=None, mods=0, players={}, player_logs=[], chat_logs=[])
server_settings = ServerSettings()
broker = Broker()
websockets: list[asyncio.Task] = []
temp_files: dict[str, TempFile] = {}

async def run_command(command_str: str) -> None:
    """
    Sends a command to the BeamMP server.
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

def reset_server_data() -> None :
    """
    Resets server_data to its default state.
    """
    global server_data
    server_data = ServerData()

def reset_server_settings() -> None:
    """
    Clears all settings from server_settings.
    """
    global server_settings
    server_settings = ServerSettings()

async def start_server() -> None:
    """
    Starts the BeamMP Server.
    """
    old_data_dict = server_data.model_dump(exclude={"process"})
    old_data = ServerData.model_validate(copy.deepcopy(old_data_dict))
    async with aiofiles.open("Server.log", "w") as file:
        await file.writelines("")
    reset_server_settings()
    reset_server_data()
    await send_changed_data(old_data)
    server_data.process = await asyncio.subprocess.create_subprocess_exec(configuration.beammp_executable_path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.PIPE)

async def write_config() -> None:
    """
    Writes the configuration to disk asynchronously.
    """
    to_write = configuration.model_dump_json(indent=5)
    async with aiofiles.open("config.json", "w") as file:
        await file.write(to_write)

# -- Website routes --

@app.route(f"{configuration.url_base_path}/")
async def main_page():
    return redirect(f"{configuration.url_base_path}/dashboard")

@app.route(f"{configuration.url_base_path}/dashboard")
@login_required
async def dashboard():
    return await render_template("dashboard.html", base=configuration.url_base_path)

@app.route(f"{configuration.url_base_path}/guest_dashboard")
async def guest_dashboard():
    if not configuration.public_dashboard:
        return abort(404)
    return await render_template("guest_dashboard.html", base=configuration.url_base_path)

@app.route(f"{configuration.url_base_path}/mods_list")
async def guest_mods():
    if not configuration.public_dashboard:
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
    uri = oauth_client.generate_uri(skip_prompt=True, scope=["identify"])
    return redirect(uri)

@app.route(f"{configuration.url_base_path}/login/oauth2")
async def oauth_login():
    session.permanent = True
    app.permanent_session_lifetime = datetime.timedelta(seconds=30)
    session["error"] = "error"

    code = request.args.get("code")
    if code is None:
        return redirect(f"{configuration.url_base_path}/login")

    access = await oauth_client.exchange_code(code)
    identify = await access.fetch_identify()
    if "id" in identify:
        if int(identify["id"]) in configuration.authorized_users:
            auth = AuthUser(identify["id"])
            login_user(auth, True)
            session.pop("error")
            return redirect(f"{configuration.url_base_path}/dashboard")
        session["error"] = "unauthorized"
    return redirect(f"{configuration.url_base_path}/login")

@app.route(f"{configuration.url_base_path}/logout")
async def logout():
    logout_user()
    return redirect(f"{configuration.url_base_path}/login")

@app.route(f"{configuration.url_base_path}/static/<string:folder>/<string:filename>")
async def get_static_file(folder: str, filename: str):
    authenticated = await current_user.is_authenticated
    if folder == "css":
        if not authenticated and filename not in ("guest_dashboard.css", "login.css"):
            return abort(401)
        if not configuration.public_dashboard and filename == "guest_dashboard.css":
            return abort(404)
        path = safe_join("static/css/", filename)
    elif folder == "images":
        path = safe_join("static/images/", filename)
    elif folder == "js":
        if not authenticated and filename not in ("guest_dashboard.js", "login.js"):
            return abort(401)
        if not configuration.public_dashboard and filename == "guest_dashboard.js":
            return abort(404)
        path = safe_join("static/js/", filename)
    else:
        return abort(404)
    if path is not None and await aioos.path.exists(path):
        return await send_file(path)
    return abort(404)

@app.route(f"{configuration.url_base_path}/mods/<string:filename>")
async def get_mod_file(filename: str):
    authenticated = await current_user.is_authenticated
    if not configuration.public_dashboard and not authenticated:
        return abort(401)
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
    Checks whether a zip file is valid.
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
    Searches for level information files, and returns the path if found.
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
@login_required
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
    if not filename.endswith(".zip") or len(filename) <= 4 or len(filename) > 24:
        return abort(400)
    if filename in await aioos.listdir("Resources/Client/") or filename in await aioos.listdir("Resources/Client.disabled/"):
        return abort(409)

    if total / (1024 * 1024 * 1024) >= 1: # Max 1 GB
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
    elif filename not in temp_files or temp_files[filename].total_bytes != total:
        return abort(400)
    elif filename in temp_files and temp_files[filename].complete:
        return abort(409)

    temp_files[filename].last_write = datetime.datetime.now()

    towrite: bytes = chunk.read()
    temp_files[filename].hasher.update(towrite)
    async with aiofiles.open(temp_path, "ab") as f:
        await f.seek(start)
        await f.write(towrite)

    # Check if the file is a zip file
    if start == 0:
        async with aiofiles.open(temp_path, "rb") as f:
            header = await f.read(4)
            if not header.startswith(b'\x50\x4B\x03\x04'):
                await aioos.remove(temp_path)
                return abort(415)

    if end + 1 == total:
        hash = temp_files[filename].hasher.hexdigest()
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
                    vt_file = await client.get_object_async(f"/files/{hash}")
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
                        if await aioos.path.getsize(temp_path) >= 650000000: # Don't allow to upload files over 650MB to VirusTotal
                            return abort(413)
                        with open(temp_path, "rb") as file:
                            try:
                                await client.scan_file_async(file, wait_for_completion=True)
                                vt_file = await client.get_object_async(f"/files/{hash}")
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
            if level is not None and level not in configuration.levels:
                configuration.levels.append(level)
                await write_config() # Write the new level to the disk

        final_path = safe_join("Resources/Client/", filename)
        shutil.move(temp_path, final_path)
        del temp_files[filename]
        await run_command("reloadmods")
        return Response(filename, 201)

    return Response("Chunk stored", 206)

# -- Data Websocket --

async def process_websocket_request(ws_request: str) -> dict[str] | typing.Literal[True] | None:
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
                case "player_logs":
                    return {"player_logs": server_data.player_logs}
                case "chat_logs":
                    return {"chat_logs": server_data.chat_logs}
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
                    return {"levels": configuration.levels}
        case "command":
            if "command" not in ws_request:
                return None
            match ws_request["command"]:
                case "restart":
                    if server_data.process is not None and server_data.process.returncode is None:
                        server_data.process.terminate()
                    await start_server()
                    return {"action": "restart"}
                case "stop":
                    if server_data.process is not None:
                        server_data.process.terminate()
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

            # Reload mods to update mods list
            await run_command("reloadmods")

            return {"success": True, "action": "enable"}
        case "disable":
            if "disable" not in ws_request:
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

            return {"success": True, "action": "disable"}
        case "delete":
            if "delete" not in ws_request:
                return None
            disabled = False
            path = safe_join("Resources/Client/", ws_request["delete"])
            if path is None or not await aioos.path.exists(path):
                path = safe_join("Resources/Client.disabled/", ws_request["delete"])
                disabled = True
            if path is None or not await aioos.path.exists(path):
                return {"action": "enable", "success": False}
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
                # Reload mods to update mods list if deleted mod was enabled
                await run_command("reloadmods")

            return {"success": True, "action": "delete"}
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
            if hasattr(server_settings, ws_request["setting"]):
                if type(ws_request["value"]) is not type(getattr(server_settings, ws_request["setting"])):
                    return None
                if server_data.process is not None:
                    await run_command(f"settings set General {ws_request["setting"]} {json.dumps(ws_request["value"])}")

                    # Save the setting change to disk so it is preserved after restart
                    if configuration.preserve_settings_changes and os.path.exists("ServerConfig.toml"):
                        async with aiofiles.open("ServerConfig.toml") as file:
                            toml_str = await file.read()
                        toml = tomlkit.parse(toml_str)
                        toml["General"][ws_request["setting"]] = ws_request["value"]
                        to_write = tomlkit.dumps(toml)
                        async with aiofiles.open("ServerConfig.toml", "w") as file:
                            await file.write(to_write)

                    return {"action": ws_request["setting"], "type": "settings"}
                return {"action": "set", "success": False}
        case "ping":
            return True
    return None

async def receive() -> None:
    """
    Receives and processes data from a websocket.
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
@login_required
async def websocket_connect():
    try:
        task = asyncio.ensure_future(receive())
        websockets.append(task)
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

async def check_lines(old: list[str], output: list[str]) -> list[str]:
    new_lines = []
    for i, line in enumerate(output):
        if i >= len(old):
            new_lines.extend(output[i:])
            return new_lines
        if line != old[i]:
            new_lines.append(line)
    return new_lines

async def process_new_lines(new_lines: list[str]) -> None:
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
                        elif data[i - 1].lower() == "port":
                            server_data.port = int(word)

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
                        if data[i - 1] == "ID":
                            try:
                                int(word)
                            except ValueError:
                                continue
                            else:
                                server_data.players[word] = data[-1]
                                server_data.player_logs.append({"player": data[-1], "type": "join", "timestamp": " ".join(data[0:2])})
                                break
                elif " is now synced!" in line:
                    for i, word in enumerate(data):
                        if data[i + 1] == "is":
                            server_data.player_logs.append({"player": data[i], "type": "sync", "timestamp": " ".join(data[0:2])})
                            break
                elif " Connection Terminated" in line:
                    for i, word in enumerate(data):
                        if len(data) > i + 1 and data[i + 1] == "Connection":
                            for key in server_data.players:
                                name = server_data.players[key]
                                if name == word:
                                    del server_data.players[key]
                                    break
                            server_data.player_logs.append({"player": word, "type": "leave", "timestamp": " ".join(data[0:2])})
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
                server_data.chat_logs.append({"sender": sender, "receiver": receiver, "message": message, "timestamp": data[0:2]})
            else:
                print(f"Invalid log type {data[2]}")
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
                print(f"Invalid setting type {data[0]}")
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
            print("Invalid line format!")
    return

async def monitor_logs() -> None:
    """
    Monitors the Server.log file and processes any new lines.
    """
    old_lines = []

    while True:
        await asyncio.sleep(0.5)
        if server_data.process is not None and server_data.process.returncode is None:
            async with aiofiles.open("Server.log") as file:
                output = await file.read()

                # Save old data and settings to compare with afterwards
                old_data_dict = server_data.model_dump()
                old_data_dict["process"] = None # Set process to None before deep copying because it is un-pickleable
                old_data = ServerData.model_validate(copy.deepcopy(old_data_dict))
                old_settings = server_settings.model_copy(deep=True)

                new_lines = await check_lines(old_lines, output.splitlines())
                old_lines = output.splitlines()
                if len(new_lines) > 0:
                    await process_new_lines(new_lines)
                    await send_changed_data(old_data, old_settings)
                    print(f"Processed {len(new_lines)} new lines")
        elif server_data.process is not None:
            reset_server_data()

async def monitor_temp_files() -> None:
    """
    Deletes temporary files if it has been over a minute since the last write.
    """
    while True:
        await asyncio.sleep(1)
        for filename, data in temp_files.items():
            if data.last_write is not None and not data.complete and data.last_write + datetime.timedelta(minutes=1) < datetime.datetime.now():
                path = safe_join("Resources/Client.temp/", filename + ".part")
                if await aioos.path.exists(path):
                    await aioos.remove(path)
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
