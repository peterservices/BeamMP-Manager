import asyncio
import datetime
import hashlib
import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any, Literal, Self

import aiofiles
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    computed_field,
)


class AuthorizedDiscordUser(BaseModel):
    """
    A model representing a user authorized to access the dashboard.
    """
    permissions: list[Literal["modify_settings", "modify_mods", "manage_server", "clear_logs", "configure"]] = ["modify_settings", "modify_mods", "manage_server"]

class LocalConfiguration(BaseModel):
    """
    A model representing the local configuration file.
    """
    authorized_discord_users: dict[int, AuthorizedDiscordUser] = {}
    beammp_executable_path: str = "BeamMP-Server"
    detect_mod_maps: bool = True
    discord_oauth2_redirect_url: str = ""
    maximum_log_entries: PositiveInt = 500
    persist_data: bool = True
    preserve_setting_changes: bool = True
    public_dashboard: bool = True
    require_login: bool = True
    url_base_path: str = "/beammp"
    virustotal_scanning: bool = True

class PersistentData(BaseModel):
    """
    A model representing data that will be saved to disk and persist across sessions.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def dump_and_write(self: Self, filename: str = "persistent_data.json") -> None:
        """
        Dump the model and write the JSON to disk asynchronously.
        """
        async with self.lock:
            to_write = self.model_dump_json(indent=4)
            async with aiofiles.open(filename, "w") as file:
                await file.write(to_write)

    async def trim_logs(self: Self, maximum_log_entries: int) -> bool:
        """
        Ensure the length of the logs don't exceed the configured limit. Returns whether any changes were made.
        """
        changes = False
        logs_length = len(self.logs)
        if logs_length > maximum_log_entries:
            end_index = logs_length - maximum_log_entries
            async with self.lock:
                del self.logs[0:end_index]
            changes = True
        return changes

    async def verify_levels(self: Self) -> bool:
        """
        Ensure all level filepaths are associated to a mod file, and remove them if not. Returns whether any changes were made.
        """
        changes = False
        async with aiofiles.open("Resources/Client/mods.json") as file:
            mods_json = await file.read()
        mods: dict[str, dict[str]] | None = json.loads(mods_json)
        if mods is not None:
            hashes = set()
            for _, v in mods.items():
                hashes.add(v["hash"])

            async with self.lock:
                for key, value in self.levels.copy().items():
                    if value is not None:
                        for mod_hash in value.copy():
                            if mod_hash not in hashes:
                                value.remove(mod_hash)
                        if len(value) == 0:
                            del self.levels[key]
                            changes = True
        return changes

    async def add_level_hash(self: Self, file_hash: str, level: str) -> bool:
        """
        Add a file hash and it's level. Returns whether any changes were made.
        """
        changes = False
        async with self.lock:
            if level in self.levels and file_hash not in self.levels[level]:
                self.levels[level].append(file_hash)
                changes = True
            elif level not in self.levels:
                self.levels[level] = [file_hash]
                changes = True
        return changes

    async def remove_level_hash(self: Self, file_hash: str) -> bool:
        """
        Remove a file hash from associated levels. Returns whether any changes were made.
        """
        changes = False
        async with self.lock:
            for key, value in self.levels.copy().items():
                if value is not None and file_hash in value:
                    value.remove(file_hash)
                    if len(value) == 0:
                        del self.levels[key]
                        changes = True
        return changes

    lock: asyncio.Lock = Field(default_factory=asyncio.Lock, exclude=True)
    levels: dict[str, list[str] | None] = {
        "/levels/automation_test_track/info.json": None,
        "/levels/cliff/info.json": None,
        "/levels/derby/info.json": None,
        "/levels/driver_training/info.json": None,
        "/levels/east_coast_usa/info.json": None,
        "/levels/gridmap_v2/info.json": None,
        "/levels/hirochi_raceway/info.json": None,
        "/levels/industrial/info.json": None,
        "/levels/italy/info.json": None,
        "/levels/johnson_valley/info.json": None,
        "/levels/jungle_rock_island/info.json": None,
        "/levels/small_island/info.json": None,
        "/levels/smallgrid/info.json": None,
        "/levels/utah/info.json": None,
        "/levels/west_coast_usa/info.json": None,
    }
    logs: list[dict[str, str]] = []

class ServerData(BaseModel):
    """
    A model representing a BeamMP server's state.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    persistent_data: PersistentData | None = Field(default=None, exclude=True)
    process: asyncio.subprocess.Process | None = Field(default=None, exclude=True)
    connected: bool = False
    started: bool = False
    error: bool = False
    version: str | None = None
    lua_version: str | None = None
    port: int | None = None
    max_clients: int | None = None
    mods: int = 0
    beampaint_installed: bool = False
    players: dict[str, str] = {}

    @computed_field
    @property
    def levels(self: Self) -> list[str] | None:
        if self.persistent_data is None:
            return None
        return list(self.persistent_data.levels.keys())

    @computed_field
    @property
    def logs(self: Self) -> list[dict[str, str]] | None:
        if self.persistent_data is None:
            return None
        return self.persistent_data.logs

class ServerSettings(BaseModel):
    """
    A model representing a BeamMP server's settings.
    """
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
    """
    A model representing a temporary file during download.
    """
    @staticmethod
    def _validate_hash_obj(obj: object) -> object:
        """
        Validate that the object is a HASH object.
        """
        # Check if the object has the attributes of a HASH object, because there is no HASH type to compare against
        if hasattr(obj, "update") and hasattr(obj, "digest") and hasattr(obj, "hexdigest") and hasattr(obj, "copy"):
            return obj
        raise ValueError("Must be a HASH object!")

    total_bytes: int
    user: str
    hasher: Annotated[object, AfterValidator(_validate_hash_obj)] = Field(default_factory=hashlib.sha256)
    expected_next_byte: int = 0
    complete: bool = False
    last_write: datetime.datetime | None = None

class ReleaseFile(BaseModel):
    """
    A model representing an available file for a GitHub release.
    """
    platform: str
    architecture: str
    download_url: str
    size: int

class ReleaseCache(BaseModel):
    """
    A model representing a cached GitHub release.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    lock: asyncio.Lock = Field(default_factory=asyncio.Lock, exclude=True)
    last_cache: datetime.datetime | None = Field(default=None, exclude=True)
    version: str | None = None
    files: list[ReleaseFile] = []

class Broker:
    def __init__(self: Self) -> None:
        self.connections: set[asyncio.Queue] = set()

    async def event(self: Self, data: dict[str, Any] | None) -> None:
        if data is not None: # If data is None, it is a shutdown request and shouldn't be serialized
            data = json.dumps(data)

        # Send event data
        for connection in self.connections.copy():
            await connection.put(data)

    async def subscribe(self: Self) -> AsyncGenerator[str, None]:
        connection = asyncio.Queue()
        self.connections.add(connection)
        try:
            while True:
                yield await connection.get()
        finally:
            self.connections.remove(connection)

# By @peterservices
