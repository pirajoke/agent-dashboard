"""Bounded, privacy-safe projection of native agent turn metadata.

The adapter deliberately reads only JSONL envelope metadata needed to prove a
turn transition.  Prompt, message and tool bodies are never copied into the
checkpoint.  Missing or ambiguous evidence fails closed.
"""
from __future__ import annotations

import ctypes
from datetime import datetime, timedelta, timezone
import heapq
import hashlib
import json
import os
from pathlib import Path
import re
import select
import sqlite3
import stat as stat_module
import subprocess
import time
from typing import Any, Callable, Iterator, NamedTuple


SCHEMA = "manager_native_activity_v1"
ROUTE_SCHEMA = "main_manager_agent_routes_v1"
FRESH_FOR = timedelta(minutes=5)
MAX_FUTURE_SKEW = timedelta(0)
DEFAULT_MAX_FILES = 64
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
MAX_FILES_CEILING = 256
MAX_BYTES_CEILING = 16 * 1024 * 1024
_MAX_DIRECTORY_FACTOR = 8
_MAX_ENTRY_FACTOR = 64
_MAX_CONFIGURED_ROOTS = 16
_GLOBAL_BYTE_MULTIPLIER = 4
_ROUTE_REGISTRY_MAX_BYTES = 1024 * 1024
_PROCESS_OUTPUT_MAX_BYTES = 16 * 1024
_PROCESS_TIMEOUT_SECONDS = 2.0
_PROCESS_RECORD_LIMIT = 32
_PROC_PIDPATH_BUFFER_SIZE = 4096
_LIFECYCLE_QUERY_TIMEOUT_SECONDS = 0.2
_LIFECYCLE_PROGRESS_INSTRUCTIONS = 1000
_LIFECYCLE_COLUMNS = frozenset(
    {"thread_id", "rollout_ordinal", "status", "started_at", "completed_at"}
)

ROUTE_CONTRACT = (
    ("accountable-os", "ACCOUNTABLE OS", "finance", "ANALYST"),
    ("ai-studio", "AI STUDIO", "hq", "COORDINATOR"),
    ("context-news", "CONTEXT_NEWS", "development", "BUILDER"),
    ("financial-os", "FINANCIAL OS", "finance", "ANALYST"),
    ("github-hygiene", "GITHUB HYGIENE", "infrastructure", "ANALYST"),
    ("health-os", "HEALTH OS", "internal", "ANALYST"),
    ("jarvis", "JARVIS", "infrastructure", "BUILDER"),
    ("main-manager", "MAIN MANAGER", "hq", "COORDINATOR"),
    ("my-dictionary", "MY DICTIONARY", "development", "BUILDER"),
    ("pixelverse-dashboard", "PIXELVERSE DASHBOARD", "infrastructure", "BUILDER"),
    ("skills-library", "SKILLS LIBRARY", "internal", "RESEARCHER"),
    ("unfinished-stuff", "UNFINISHED STUFF", "internal", "COORDINATOR"),
)
PUBLIC_AGENT_FIELDS = (
    "route_id",
    "project",
    "department_id",
    "agent_role",
    "state",
    "availability",
    "freshness",
    "state_at",
    "outcome_stage",
)

_SAFE_ROUTE_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_SAFE_HASH = re.compile(r"^[0-9a-f]{64}$")
_JSON_NUMBER = re.compile(rb"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_PROGRESS_TYPES = frozenset(
    {
        "assistant",
        "function_call",
        "function_call_output",
        "reasoning",
        "tool_result",
        "tool_use",
        "custom_tool_call",
        "custom_tool_call_output",
    }
)


class NativeActivityError(RuntimeError):
    """The native source could not be safely projected."""


class _SourceCandidate(NamedTuple):
    source: str
    path: Path
    modified_ns: int
    device: int
    inode: int


class _LifecycleTurn(NamedTuple):
    status: str
    started_at: int | None
    completed_at: int | None


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return _utc(moment).isoformat().replace("+00:00", "Z")


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


class _EnvelopeJsonError(ValueError):
    pass


class _EnvelopeJsonParser:
    """Validate one JSON object while decoding only allowlisted envelope strings."""

    _TOP_FIELDS = {
        b'"timestamp"': "timestamp",
        b'"created_at"': "created_at",
        b'"updated_at"': "updated_at",
        b'"type"': "type",
        b'"sessionId"': "sessionId",
        b'"session_id"': "session_id",
        b'"threadId"': "threadId",
        b'"thread_id"': "thread_id",
        b'"payload"': "payload",
    }
    _PAYLOAD_FIELDS = {
        b'"type"': "type",
        b'"id"': "id",
        b'"session_id"': "session_id",
        b'"parent_thread_id"': "parent_thread_id",
        b'"forked_from_id"': "forked_from_id",
    }

    def __init__(self, data: bytes | memoryview):
        self.data = data if isinstance(data, memoryview) else memoryview(data)
        self.pos = 0

    def parse(self) -> dict[str, Any]:
        result = self._selected_object(self._TOP_FIELDS, top_level=True, depth=0)
        self._whitespace()
        if self.pos != len(self.data):
            raise _EnvelopeJsonError("trailing_json")
        return result

    def _whitespace(self) -> None:
        while self.pos < len(self.data) and self.data[self.pos] in b" \t\r\n":
            self.pos += 1

    def _take(self, expected: int) -> None:
        self._whitespace()
        if self.pos >= len(self.data) or self.data[self.pos] != expected:
            raise _EnvelopeJsonError("invalid_json")
        self.pos += 1

    def _matches(self, literal: bytes, start: int | None = None) -> bool:
        offset = self.pos if start is None else start
        if offset < 0 or offset + len(literal) > len(self.data):
            return False
        return all(self.data[offset + index] == byte for index, byte in enumerate(literal))

    def _string_token(self, *, capture: bool = True) -> bytes | None:
        self._whitespace()
        if self.pos >= len(self.data) or self.data[self.pos] != ord('"'):
            raise _EnvelopeJsonError("string_required")
        start = self.pos
        self.pos += 1
        while self.pos < len(self.data):
            byte = self.data[self.pos]
            if byte == ord('"'):
                self.pos += 1
                return bytes(self.data[start:self.pos]) if capture else None
            if byte < 0x20:
                raise _EnvelopeJsonError("invalid_string")
            if byte == ord("\\"):
                self.pos += 1
                if self.pos >= len(self.data) or self.data[self.pos] not in b'"\\/bfnrtu':
                    raise _EnvelopeJsonError("invalid_escape")
                if self.data[self.pos] == ord("u"):
                    if self.pos + 4 >= len(self.data):
                        raise _EnvelopeJsonError("invalid_unicode_escape")
                    if any(
                        self.data[index] not in b"0123456789abcdefABCDEF"
                        for index in range(self.pos + 1, self.pos + 5)
                    ):
                        raise _EnvelopeJsonError("invalid_unicode_escape")
                    self.pos += 4
            elif byte >= 0x80:
                self.pos = self._utf8_scalar_end(self.pos) - 1
            self.pos += 1
        raise _EnvelopeJsonError("unterminated_string")

    def _utf8_scalar_end(self, start: int) -> int:
        """Validate one UTF-8 scalar without decoding or retaining its value."""
        lead = self.data[start]
        if 0xC2 <= lead <= 0xDF:
            length = 2
            second_min, second_max = 0x80, 0xBF
        elif lead == 0xE0:
            length = 3
            second_min, second_max = 0xA0, 0xBF
        elif 0xE1 <= lead <= 0xEC or 0xEE <= lead <= 0xEF:
            length = 3
            second_min, second_max = 0x80, 0xBF
        elif lead == 0xED:
            length = 3
            second_min, second_max = 0x80, 0x9F
        elif lead == 0xF0:
            length = 4
            second_min, second_max = 0x90, 0xBF
        elif 0xF1 <= lead <= 0xF3:
            length = 4
            second_min, second_max = 0x80, 0xBF
        elif lead == 0xF4:
            length = 4
            second_min, second_max = 0x80, 0x8F
        else:
            raise _EnvelopeJsonError("invalid_utf8")
        end = start + length
        if end > len(self.data) or not second_min <= self.data[start + 1] <= second_max:
            raise _EnvelopeJsonError("invalid_utf8")
        if any(not 0x80 <= byte <= 0xBF for byte in self.data[start + 2:end]):
            raise _EnvelopeJsonError("invalid_utf8")
        return end

    @staticmethod
    def _selected_string(token: bytes) -> str:
        body = token[1:-1]
        if b"\\" in body:
            raise _EnvelopeJsonError("escaped_metadata")
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise _EnvelopeJsonError("invalid_metadata_encoding") from error

    def _selected_object(
        self,
        fields: dict[bytes, str],
        *,
        top_level: bool,
        depth: int,
    ) -> dict[str, Any]:
        if depth > 32:
            raise _EnvelopeJsonError("json_too_deep")
        self._take(ord("{"))
        result: dict[str, Any] = {}
        seen: set[str] = set()
        self._whitespace()
        if self.pos < len(self.data) and self.data[self.pos] == ord("}"):
            self.pos += 1
            return result
        while True:
            key = self._selected_field(fields)
            self._take(ord(":"))
            if key is None:
                self._skip_value(depth + 1)
            else:
                if key in seen:
                    raise _EnvelopeJsonError("duplicate_metadata")
                seen.add(key)
                if top_level and key == "payload":
                    self._whitespace()
                    if self.pos < len(self.data) and self.data[self.pos] == ord("{"):
                        result[key] = self._selected_object(
                            self._PAYLOAD_FIELDS,
                            top_level=False,
                            depth=depth + 1,
                        )
                    else:
                        self._skip_value(depth + 1)
                        result[key] = None
                else:
                    token = self._string_token(capture=True)
                    if token is None:
                        raise _EnvelopeJsonError("string_required")
                    result[key] = self._selected_string(token)
            self._whitespace()
            if self.pos >= len(self.data):
                raise _EnvelopeJsonError("unterminated_object")
            delimiter = self.data[self.pos]
            self.pos += 1
            if delimiter == ord("}"):
                return result
            if delimiter != ord(","):
                raise _EnvelopeJsonError("invalid_object")

    def _selected_field(self, fields: dict[bytes, str]) -> str | None:
        """Validate a key without returning or copying an unallowlisted token."""
        self._whitespace()
        start = self.pos
        self._string_token(capture=False)
        end = self.pos
        for encoded, field in fields.items():
            if end - start == len(encoded) and self._matches(encoded, start):
                return field
        return None

    def _skip_value(self, depth: int) -> None:
        if depth > 32:
            raise _EnvelopeJsonError("json_too_deep")
        self._whitespace()
        if self.pos >= len(self.data):
            raise _EnvelopeJsonError("missing_value")
        byte = self.data[self.pos]
        if byte == ord('"'):
            self._string_token(capture=False)
            return
        if byte == ord("{"):
            self.pos += 1
            self._whitespace()
            if self.pos < len(self.data) and self.data[self.pos] == ord("}"):
                self.pos += 1
                return
            while True:
                self._string_token(capture=False)
                self._take(ord(":"))
                self._skip_value(depth + 1)
                self._whitespace()
                if self.pos >= len(self.data):
                    raise _EnvelopeJsonError("unterminated_object")
                delimiter = self.data[self.pos]
                self.pos += 1
                if delimiter == ord("}"):
                    return
                if delimiter != ord(","):
                    raise _EnvelopeJsonError("invalid_object")
        if byte == ord("["):
            self.pos += 1
            self._whitespace()
            if self.pos < len(self.data) and self.data[self.pos] == ord("]"):
                self.pos += 1
                return
            while True:
                self._skip_value(depth + 1)
                self._whitespace()
                if self.pos >= len(self.data):
                    raise _EnvelopeJsonError("unterminated_array")
                delimiter = self.data[self.pos]
                self.pos += 1
                if delimiter == ord("]"):
                    return
                if delimiter != ord(","):
                    raise _EnvelopeJsonError("invalid_array")
        for literal in (b"true", b"false", b"null"):
            if self._matches(literal):
                self.pos += len(literal)
                return
        match = _JSON_NUMBER.match(self.data, self.pos)
        if match is None:
            raise _EnvelopeJsonError("invalid_value")
        self.pos = match.end()


def _parse_jsonl_envelope(line: bytes | memoryview) -> dict[str, Any]:
    return _EnvelopeJsonParser(line).parse()


def _empty_agent(route: tuple[str, str, str, str]) -> dict[str, Any]:
    route_id, project, department_id, agent_role = route
    return {
        "route_id": route_id,
        "project": project,
        "department_id": department_id,
        "agent_role": agent_role,
        "state": None,
        "availability": "unavailable",
        "freshness": "unavailable",
        "state_at": None,
        "outcome_stage": None,
    }


def _read_route_registry(path: Path) -> tuple[bytes, dict[str, str]]:
    try:
        opened = _read_regular_file(path, limit=_ROUTE_REGISTRY_MAX_BYTES)
        if opened is None:
            raise NativeActivityError("route_registry_unavailable")
        raw, _ = opened
        if not raw or len(raw) > _ROUTE_REGISTRY_MAX_BYTES:
            raise NativeActivityError("route_registry_invalid")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, RecursionError) as error:
        raise NativeActivityError("route_registry_invalid") from error
    if (
        not isinstance(data, dict)
        or data.get("schema") != ROUTE_SCHEMA
        or data.get("version") != 1
        or not isinstance(data.get("routes"), dict)
    ):
        raise NativeActivityError("route_registry_invalid")

    enabled: list[tuple[str, str, str, str]] = []
    private_threads: dict[str, str] = {}
    for route_id, record in data["routes"].items():
        if not isinstance(record, dict) or record.get("enabled") is not True:
            continue
        identity = (
            route_id,
            record.get("project"),
            record.get("departmentId"),
            record.get("agentRole"),
        )
        if (
            not isinstance(route_id, str)
            or _SAFE_ROUTE_ID.fullmatch(route_id) is None
            or not all(isinstance(value, str) for value in identity)
        ):
            raise NativeActivityError("route_registry_invalid")
        enabled.append(identity)
        thread_id = record.get("threadId")
        if not isinstance(thread_id, str) or not thread_id or thread_id in private_threads:
            raise NativeActivityError("route_registry_invalid")
        private_threads[thread_id] = route_id
    if tuple(enabled) != ROUTE_CONTRACT:
        raise NativeActivityError("route_registry_mismatch")
    return raw, private_threads


def _read_lifecycle_snapshot(
    path: Path,
    *,
    thread_routes: dict[str, str],
) -> dict[str, _LifecycleTurn] | None:
    """Read only the latest allowlisted turn fields in one SQLite snapshot."""
    try:
        before = path.lstat()
    except OSError:
        return None
    if not stat_module.S_ISREG(before.st_mode):
        return None

    connection: sqlite3.Connection | None = None
    transaction = False
    try:
        # ``absolute`` does not follow the final path component. The lstat
        # checks before and after the transaction reject links and replacement.
        uri = path.absolute().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=0.2, isolation_level=None)
        deadline = time.monotonic() + _LIFECYCLE_QUERY_TIMEOUT_SECONDS
        connection.set_progress_handler(
            lambda: int(time.monotonic() > deadline),
            _LIFECYCLE_PROGRESS_INSTRUCTIONS,
        )
        connection.execute("PRAGMA query_only = ON")
        if connection.execute("PRAGMA query_only").fetchone() != (1,):
            return None
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("BEGIN")
        transaction = True

        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(thread_turns)")
            if len(row) >= 2 and isinstance(row[1], str)
        }
        if not _LIFECYCLE_COLUMNS.issubset(columns):
            return None

        thread_ids = tuple(sorted(thread_routes))
        placeholders = ",".join("?" for _ in thread_ids)
        query = f"""
            SELECT current.thread_id, current.status, current.started_at,
                   current.completed_at, current.rollout_ordinal
              FROM thread_turns AS current
             WHERE current.thread_id IN ({placeholders})
               AND current.rollout_ordinal = (
                   SELECT MAX(candidate.rollout_ordinal)
                     FROM thread_turns AS candidate
                    WHERE candidate.thread_id = current.thread_id
               )
             ORDER BY current.thread_id
             LIMIT ?
        """
        rows = connection.execute(query, (*thread_ids, len(thread_ids) + 1)).fetchall()
        connection.execute("COMMIT")
        transaction = False

        after = path.lstat()
        if (
            not stat_module.S_ISREG(after.st_mode)
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or len(rows) > len(thread_ids)
        ):
            return None

        snapshot: dict[str, _LifecycleTurn] = {}
        for thread_id, status, started_at, completed_at, rollout_ordinal in rows:
            if (
                not isinstance(thread_id, str)
                or thread_id not in thread_routes
                or thread_routes[thread_id] in snapshot
                or not isinstance(status, str)
                or type(rollout_ordinal) is not int
                or type(started_at) not in {int, type(None)}
                or type(completed_at) not in {int, type(None)}
            ):
                return None
            snapshot[thread_routes[thread_id]] = _LifecycleTurn(
                status=status,
                started_at=started_at,
                completed_at=completed_at,
            )
        return snapshot
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None
    finally:
        if connection is not None:
            if transaction:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            connection.close()


def _read_regular_file(path: Path, *, limit: int) -> tuple[bytes, os.stat_result] | None:
    """Read one bounded regular file while refusing a final-component symlink."""
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        return None
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | no_follow)
        info = os.fstat(descriptor)
        if not stat_module.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > limit:
            return None
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            raw = handle.read(limit + 1)
        if len(raw) != info.st_size or len(raw) > limit:
            return None
        return raw, info
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _iter_jsonl_files(roots: dict[str, list[Path]], max_files: int) -> Iterator[_SourceCandidate]:
    """Yield bounded JSONL candidates, retaining symlinks only as rejection evidence."""
    if not isinstance(roots, dict):
        raise NativeActivityError("native_scan_roots_invalid")
    configured: list[tuple[str, Path]] = []
    for source in sorted(key for key in roots if isinstance(key, str)):
        raw_roots = roots.get(source)
        if not isinstance(raw_roots, (list, tuple)):
            continue
        for raw_root in raw_roots:
            if isinstance(raw_root, (str, os.PathLike)):
                configured.append((source, Path(raw_root)))
    if not configured:
        return
    if len(configured) > _MAX_CONFIGURED_ROOTS:
        raise NativeActivityError("native_scan_roots_exceed_bound")
    quota = max(1, (max_files + len(configured) - 1) // len(configured))
    candidate_groups: list[list[tuple[int, str, str, Path, int, int]]] = []
    for source, root in configured:
        try:
            if root.is_symlink() or not root.is_dir():
                continue
        except OSError:
            continue
        directory_budget = max(1, quota * _MAX_DIRECTORY_FACTOR)
        entry_budget = max(64, quota * _MAX_ENTRY_FACTOR)
        directories_seen = 0
        entries_seen = 0
        pending = [root]
        root_candidates: list[tuple[int, str, Path, int, int]] = []
        while pending and directories_seen < directory_budget and entries_seen < entry_budget:
            directory = pending.pop()
            directories_seen += 1
            try:
                entries = os.scandir(directory)
            except OSError:
                continue
            with entries:
                for entry in entries:
                    entries_seen += 1
                    if entries_seen > entry_budget:
                        break
                    try:
                        is_symlink = entry.is_symlink()
                        if is_symlink and not entry.name.endswith(".jsonl"):
                            continue
                        if not is_symlink and entry.is_dir(follow_symlinks=False):
                            if len(pending) < directory_budget:
                                pending.append(Path(entry.path))
                            continue
                        if (
                            not is_symlink
                            and (
                                not entry.is_file(follow_symlinks=False)
                                or not entry.name.endswith(".jsonl")
                            )
                        ):
                            continue
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    candidate = (
                        info.st_mtime_ns,
                        entry.name,
                        Path(entry.path),
                        info.st_dev,
                        info.st_ino,
                    )
                    if len(root_candidates) < quota:
                        heapq.heappush(root_candidates, candidate)
                    elif candidate[:2] > root_candidates[0][:2]:
                        heapq.heapreplace(root_candidates, candidate)
        group = [
            (mtime, source, name, path, device, inode)
            for mtime, name, path, device, inode in root_candidates
        ]
        group.sort(key=lambda item: (-item[0], item[2]))
        candidate_groups.append(group)
    yielded = 0
    for offset in range(max((len(group) for group in candidate_groups), default=0)):
        for group in candidate_groups:
            if offset < len(group):
                modified_ns, source, _, path, device, inode = group[offset]
                yield _SourceCandidate(source, path, modified_ns, device, inode)
                yielded += 1
                if yielded >= max_files:
                    return


def _rejected_candidate_order(candidate: _SourceCandidate) -> tuple[int, bool]:
    """Return rejection order and whether a scan/read replacement made it ambiguous."""
    try:
        current = candidate.path.lstat()
    except OSError:
        return candidate.modified_ns, True
    replaced = (
        current.st_dev != candidate.device
        or current.st_ino != candidate.inode
        or current.st_mtime_ns != candidate.modified_ns
    )
    return max(candidate.modified_ns, current.st_mtime_ns), replaced


def _record_identities(record: dict[str, Any]) -> set[str]:
    identities: set[str] = set()
    record_type = record.get("type")
    payload = record.get("payload")
    if record_type == "session_meta" and isinstance(payload, dict):
        for key in ("id", "session_id", "parent_thread_id", "forked_from_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                identities.add(value)
    for key in ("sessionId", "session_id", "threadId", "thread_id"):
        value = record.get(key)
        if isinstance(value, str) and value:
            identities.add(value)
    return identities


def _transition(record: dict[str, Any]) -> str | None:
    record_type = record.get("type")
    payload = record.get("payload")
    payload_type = payload.get("type") if isinstance(payload, dict) else None
    if record_type == "event_msg" and payload_type == "task_started":
        return "started"
    if record_type == "event_msg" and payload_type == "task_complete":
        return "completed"
    if record_type == "response_item" and payload_type in _PROGRESS_TYPES:
        return "progress"
    # Claude JSONL uses envelope types instead of Codex event_msg records.
    if record_type == "user":
        return "started"
    if record_type in _PROGRESS_TYPES:
        return "progress"
    return None


def _jsonl_line_views(raw: bytes) -> Iterator[memoryview]:
    """Yield non-blank line views without copying private JSONL bodies."""
    view = memoryview(raw)
    start = 0
    for offset in range(len(view) + 1):
        if offset < len(view) and view[offset] != ord("\n"):
            continue
        line = view[start:offset]
        start = offset + 1
        if any(byte not in b" \t\r\n" for byte in line):
            yield line


def _read_source_window(path: Path, limit: int, bytes_read: list[int]) -> tuple[bytes, os.stat_result, bool, int] | None:
    """Read stable small sources or a bounded Codex owner header and tail."""
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None or limit <= 0:
        return None
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | no_follow)
        before = os.fstat(descriptor)
        if not stat_module.S_ISREG(before.st_mode) or before.st_size <= 0:
            return None
        windowed = before.st_size > limit
        with os.fdopen(descriptor, "rb", buffering=0, closefd=True) as handle:
            descriptor = None
            if not windowed:
                raw = handle.read(limit)
                consumed = len(raw)
                bytes_read[0] += consumed
                if len(raw) != before.st_size:
                    return None
            else:
                # Keep aggregate scanning practical without increasing configured bounds.
                budget = min(limit, 1024 * 1024)
                if budget <= 4:
                    return None
                prefix = handle.read(min(64 * 1024, budget // 4) - 1)
                bytes_read[0] += len(prefix)
                boundary = prefix.find(b"\n")
                if boundary < 0:
                    return None
                header = prefix[:boundary + 1]
                envelope = _parse_jsonl_envelope(header)
                payload = envelope.get("payload")
                if envelope.get("type") != "session_meta" or not isinstance(payload, dict):
                    return None
                owner = payload.get("id")
                if not isinstance(owner, str) or not owner:
                    return None
                if payload.get("session_id", owner) != owner:
                    return None
                # Validate every complete line we already read. Only incomplete
                # boundary fragments and the unread middle are omitted. The native
                # append-only format makes the initial session header authoritative;
                # this is not a full-file audit of the skipped history.
                complete_prefix = prefix[:prefix.rfind(b"\n") + 1]
                for line in list(_jsonl_line_views(complete_prefix))[1:]:
                    visible = _parse_jsonl_envelope(line)
                    if _record_identities(visible) - {owner}:
                        return None
                tail_size = budget - len(prefix) - 1
                if tail_size <= 1:
                    return None
                handle.seek(before.st_size - tail_size - 1)
                preceding = handle.read(1)
                bytes_read[0] += len(preceding)
                tail = handle.read(tail_size)
                bytes_read[0] += len(tail)
                consumed = len(prefix) + len(preceding) + len(tail)
                # Only the leading boundary fragment may be discarded. A partial
                # final record remains visible to the parser and fails closed.
                if preceding == b"\n":
                    raw = header + tail
                else:
                    boundary = tail.find(b"\n")
                    if boundary < 0:
                        return None
                    raw = header + tail[boundary + 1:]
            after = os.fstat(handle.fileno())
        current = path.lstat()
        fingerprint = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        if fingerprint(before) != fingerprint(after) or fingerprint(before) != fingerprint(current):
            return None
        return raw, before, windowed, consumed
    except (OSError, _EnvelopeJsonError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _parse_source(
    path: Path,
    *,
    now: datetime,
    max_bytes: int,
    remaining_bytes: int,
    defer_future_validation: bool = False,
) -> tuple[dict[str, Any] | None, int]:
    read_limit = min(max_bytes, remaining_bytes)
    bytes_read = [0]
    opened = _read_source_window(path, read_limit, bytes_read)
    if opened is None:
        return None, bytes_read[0]
    raw, stat, windowed, consumed = opened

    identities: set[str] = {path.stem} if path.stem else set()
    records: list[tuple[datetime, str | None]] = []
    all_records: list[tuple[datetime, str | None]] = []
    invalid = False
    last_time: datetime | None = None
    owner: str | None = None
    window_started = not windowed
    for line in _jsonl_line_views(raw):
        try:
            record = _parse_jsonl_envelope(line)
        except _EnvelopeJsonError:
            invalid = True
            continue
        if windowed:
            payload = record.get("payload")
            if owner is None:
                owner = payload.get("id") if isinstance(payload, dict) else None
                identities = {owner} if isinstance(owner, str) else set()
            else:
                # Parent/fork metadata is not authority to reroute a sampled file.
                record_ids = _record_identities(record)
                if record_ids - {owner}:
                    invalid = True
        else:
            identities.update(_record_identities(record))
            if record.get("type") == "session_meta" and isinstance(record.get("payload"), dict):
                record_owner = record["payload"].get("id")
                if isinstance(record_owner, str) and record_owner:
                    if owner is None:
                        owner = record_owner
                    elif owner != record_owner:
                        invalid = True
        timestamp = _parse_time(
            record.get("timestamp") or record.get("created_at") or record.get("updated_at")
        )
        transition = _transition(record)
        if transition is not None and timestamp is None:
            invalid = True
            continue
        if timestamp is None:
            # Unknown envelopes cannot establish state and do not make known
            # metadata unsafe; they are otherwise ignored without inspection.
            continue
        if (
            (not defer_future_validation and timestamp > now + MAX_FUTURE_SKEW)
            or (last_time is not None and timestamp < last_time)
        ):
            invalid = True
        last_time = timestamp
        all_records.append((timestamp, transition))
        if transition == "started":
            window_started = True
        if window_started:
            records.append((timestamp, transition))
    return {
        "identities": identities,
        "records": records,
        "all_records": all_records,
        "owner": owner,
        "latest_timestamp": last_time,
        "invalid": invalid,
        "path": path,
        "modified_ns": stat.st_mtime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "size": stat.st_size,
    }, consumed


def _matches_regular_inode(path: Path, *, expected_device: int, expected_inode: int) -> bool:
    """Confirm that ``path`` still names the parsed regular file without following links."""
    try:
        current = path.lstat()
    except OSError:
        return False
    return (
        stat_module.S_ISREG(current.st_mode)
        and current.st_dev == expected_device
        and current.st_ino == expected_inode
    )


def _matches_source_snapshot(parsed: dict[str, Any]) -> bool:
    """Confirm a parsed source stayed the same regular file through attestation."""
    try:
        current = parsed["path"].lstat()
    except (KeyError, OSError, TypeError):
        return False
    return (
        stat_module.S_ISREG(current.st_mode)
        and current.st_dev == parsed.get("device")
        and current.st_ino == parsed.get("inode")
        and current.st_size == parsed.get("size")
        and current.st_mtime_ns == parsed.get("modified_ns")
    )


def _probe_process(
    process_probe: Callable[..., object],
    *,
    source: str,
    path: Path,
    expected_device: int,
    expected_inode: int,
) -> bool:
    if not _matches_regular_inode(
        path,
        expected_device=expected_device,
        expected_inode=expected_inode,
    ):
        return False
    try:
        attested = bool(process_probe(path, source=source))
    except Exception:
        return False
    return attested and _matches_regular_inode(
        path,
        expected_device=expected_device,
        expected_inode=expected_inode,
    )


def _bounded_process_output(command: list[str]) -> tuple[int, bytes] | None:
    process: subprocess.Popen | None = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if process.stdout is None:
            process.kill()
            process.wait()
            return None
        descriptor = process.stdout.fileno()
        os.set_blocking(descriptor, False)
        deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
        output = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                return None
            ready, _, _ = select.select([descriptor], [], [], remaining)
            if ready:
                chunk = os.read(
                    descriptor,
                    min(4096, _PROCESS_OUTPUT_MAX_BYTES + 1 - len(output)),
                )
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > _PROCESS_OUTPUT_MAX_BYTES:
                    process.kill()
                    process.wait()
                    return None
            elif process.poll() is not None:
                break
        return_code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        return return_code, bytes(output)
    except (OSError, subprocess.SubprocessError, ValueError):
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        return None


def _kernel_executable_path(pid: int) -> Path | None:
    """Resolve a process executable from the Darwin kernel, never from argv."""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        proc_pidpath = library.proc_pidpath
        proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        proc_pidpath.restype = ctypes.c_int
        buffer = ctypes.create_string_buffer(_PROC_PIDPATH_BUFFER_SIZE)
        length = proc_pidpath(pid, buffer, len(buffer))
        if length <= 0 or length >= len(buffer):
            return None
        decoded = os.fsdecode(buffer.raw[:length].split(b"\0", 1)[0])
        candidate = Path(decoded)
        return candidate if candidate.is_absolute() else None
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _relative_parts(candidate: Path, root: Path) -> tuple[str, ...] | None:
    if not candidate.is_absolute() or ".." in candidate.parts:
        return None
    try:
        return candidate.relative_to(root).parts
    except ValueError:
        return None


def _trusted_executable_path(source: str, executable: Path, *, home: Path | None = None) -> bool:
    """Match only reviewed native-client installation structures."""
    trusted_home = home or Path.home()
    name = executable.name.lower()
    if source == "codex":
        app_parts = _relative_parts(
            executable,
            Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli"),
        )
        if app_parts in {
            ("CodexCLI.app", "Contents", "MacOS", "codex"),
            ("bin", "codex"),
        }:
            return True
        standalone = _relative_parts(
            executable,
            trusted_home / ".codex/packages/standalone",
        )
        return bool(
            name == "codex"
            and standalone
            and (
                standalone == ("current", "bin", "codex")
                or (
                    len(standalone) == 4
                    and standalone[0] == "releases"
                    and standalone[1]
                    and standalone[2:] == ("bin", "codex")
                )
            )
        )
    if source != "claude":
        return False
    app_parts = _relative_parts(executable, Path("/Applications/Claude.app/Contents"))
    if app_parts == ("MacOS", "Claude"):
        return True
    installed = _relative_parts(
        executable,
        trusted_home / "Library/Application Support/Claude/claude-code",
    )
    if (
        installed
        and len(installed) == 6
        and installed[0]
        and installed[1]
        and installed[2:] == ("claude.app", "Contents", "MacOS", "claude")
    ):
        return True
    remote = _relative_parts(executable, trusted_home / ".claude/remote")
    if not remote:
        return False
    if len(remote) == 2 and remote[0] == "ccd-cli":
        return bool(re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]{0,127}", remote[1]))
    return bool(
        len(remote) == 3
        and remote[0] == "srv"
        and re.fullmatch(r"[0-9a-f]{40}", remote[1])
        and remote[2] == "server"
    )


def _lsof_processes(output: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield bounded PID/command pairs from lsof field output."""
    current_pid: int | None = None
    yielded = 0
    for line in output.splitlines():
        if line.startswith(b"p"):
            raw_pid = line[1:]
            parsed_pid = int(raw_pid) if raw_pid.isdigit() and len(raw_pid) <= 10 else 0
            current_pid = parsed_pid if 0 < parsed_pid <= 2_147_483_647 else None
            continue
        if current_pid is None or not line.startswith(b"c"):
            continue
        command = line[1:].strip().lower()
        if command:
            yield current_pid, command
            yielded += 1
            if yielded >= _PROCESS_RECORD_LIMIT:
                return
        current_pid = None


def _command_matches_source(source: str, command: bytes, executable: Path) -> bool:
    if source == "codex":
        return command == b"codex" or command.startswith(b"codex ")
    if source != "claude":
        return False
    if command == b"claude" or command.startswith(b"claude "):
        return True
    remote = _relative_parts(executable, Path.home() / ".claude/remote")
    return bool(
        remote
        and (
            (len(remote) == 2 and remote[0] == "ccd-cli" and command == remote[1].encode())
            or (len(remote) == 3 and remote[0] == "srv" and command == b"server")
        )
    )


def default_process_probe(path: Path, *, source: str) -> bool:
    """Prove a trusted source process owns this file, without exposing evidence."""
    if source not in {"codex", "claude"}:
        return False
    result = _bounded_process_output(["/usr/sbin/lsof", "-F", "pc", "--", str(path)])
    if result is None:
        return False
    return_code, output = result
    if return_code != 0:
        return False
    for pid, command in _lsof_processes(output):
        executable = _kernel_executable_path(pid)
        if (
            executable is not None
            and _trusted_executable_path(source, executable)
            and _command_matches_source(source, command, executable)
        ):
            return True
    return False


def _project_source(
    parsed: dict[str, Any],
    *,
    route: tuple[str, str, str, str],
    now: datetime,
    source: str,
    process_probe: Callable[..., object],
) -> dict[str, Any]:
    agent = _empty_agent(route)
    if parsed["invalid"]:
        agent["freshness"] = "invalid"
        return agent

    started: datetime | None = None
    progress: datetime | None = None
    completed: datetime | None = None
    invalid_transition = False
    for timestamp, transition in parsed["records"]:
        if transition == "started":
            started = timestamp
            progress = None
            completed = None
        elif transition == "progress":
            if started is None or completed is not None or timestamp < started:
                invalid_transition = True
            else:
                progress = timestamp
        elif transition == "completed":
            if started is None or timestamp < started:
                invalid_transition = True
            else:
                completed = timestamp
    if invalid_transition:
        agent["freshness"] = "invalid"
        return agent

    latest = completed or progress or started
    if latest is None:
        return agent
    agent["state_at"] = _iso(latest)
    agent["freshness"] = "fresh" if now - latest <= FRESH_FOR else "stale"
    if agent["freshness"] != "fresh":
        return agent
    if completed is not None:
        agent["state"] = "idle"
        agent["availability"] = "available"
        agent["outcome_stage"] = "turn_completed"
        return agent

    process_available = _probe_process(
        process_probe,
        source=source,
        path=parsed["path"],
        expected_device=parsed["device"],
        expected_inode=parsed["inode"],
    )
    # An open process is not evidence for the earlier snapshot if it appended a
    # completion (or otherwise changed the file) while being attested.
    try:
        current_stat = parsed["path"].lstat()
        stable = (current_stat.st_mtime_ns == parsed["modified_ns"]
                  and current_stat.st_size == parsed["size"])
    except OSError:
        stable = False
    if not stable:
        agent = _empty_agent(route)
        agent["freshness"] = "invalid"
        return agent
    if progress is not None and process_available:
        agent["state"] = "running"
        agent["availability"] = "available"
    elif process_available:
        agent["availability"] = "uncertain"
    return agent


def _epoch_time(value: int | None) -> datetime | None:
    if type(value) is not int:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _project_lifecycle_source(
    parsed: dict[str, Any],
    *,
    route: tuple[str, str, str, str],
    now: datetime,
    lifecycle: _LifecycleTurn | None,
) -> dict[str, Any]:
    """Combine an exact-owner lifecycle row with bounded JSONL progress."""
    agent = _empty_agent(route)
    if parsed["invalid"] or lifecycle is None:
        agent["freshness"] = "invalid"
        return agent

    started = _epoch_time(lifecycle.started_at)
    completed = _epoch_time(lifecycle.completed_at)
    if started is None or started > now:
        agent["freshness"] = "invalid"
        return agent

    if lifecycle.status == "completed":
        if completed is None or completed < started or completed > now:
            agent["freshness"] = "invalid"
            return agent
        matching_completions = [
            timestamp
            for timestamp, transition in parsed["all_records"]
            if transition == "completed" and started <= timestamp <= completed + timedelta(seconds=1)
        ]
        if not matching_completions:
            agent["freshness"] = "invalid"
            return agent
        state_at = max(completed, max(matching_completions))
        agent["state_at"] = _iso(state_at)
        agent["freshness"] = "fresh" if now - state_at <= FRESH_FOR else "stale"
        if agent["freshness"] == "fresh":
            agent["state"] = "idle"
            agent["availability"] = "available"
            agent["outcome_stage"] = "turn_completed"
        return agent

    if lifecycle.status != "inProgress" or completed is not None:
        agent["freshness"] = "invalid"
        return agent
    if now - started > FRESH_FOR:
        agent["state_at"] = _iso(started)
        agent["freshness"] = "stale"
        return agent

    relevant = [
        (timestamp, transition)
        for timestamp, transition in parsed["all_records"]
        if timestamp >= started
    ]
    if any(transition == "completed" for _, transition in relevant):
        agent["freshness"] = "invalid"
        return agent
    progress = max(
        (timestamp for timestamp, transition in relevant if transition == "progress"),
        default=None,
    )
    if progress is None:
        agent["state_at"] = _iso(started)
        agent["freshness"] = "fresh"
        agent["availability"] = "uncertain"
        return agent
    if now - progress > FRESH_FOR:
        agent["state_at"] = _iso(progress)
        agent["freshness"] = "stale"
        return agent
    agent["state"] = "running"
    agent["availability"] = "available"
    agent["freshness"] = "fresh"
    agent["state_at"] = _iso(progress)
    return agent


def collect_native_activity(
    *,
    routes_path: Path,
    roots: dict[str, list[Path]],
    now: datetime,
    lifecycle_path: Path | None = None,
    process_probe: Callable[..., object] = default_process_probe,
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Collect an allowlisted full roster from bounded native JSONL metadata."""
    current = _utc(now)
    lifecycle_enabled = lifecycle_path is not None
    scan_started = time.monotonic() if lifecycle_enabled else None
    if (
        type(max_files) is not int
        or not 0 < max_files <= MAX_FILES_CEILING
        or type(max_bytes) is not int
        or not 0 < max_bytes <= MAX_BYTES_CEILING
    ):
        raise NativeActivityError("native_scan_bounds_invalid")
    raw_registry, thread_routes = _read_route_registry(Path(routes_path))
    agents = {route[0]: _empty_agent(route) for route in ROUTE_CONTRACT}
    observations: dict[str, tuple[int, str, dict[str, Any]]] = {}
    rejected_after: dict[str, int] = {}
    rejected_all: set[str] = set()
    unknown_rejected_after: int | None = None
    unknown_rejected_all = False
    remaining_bytes = max_bytes * min(max_files, _GLOBAL_BYTE_MULTIPLIER)

    def reject(candidate: _SourceCandidate, *, replaced: bool = False) -> None:
        nonlocal unknown_rejected_after, unknown_rejected_all
        modified_ns, ambiguous = _rejected_candidate_order(candidate)
        ambiguous = ambiguous or replaced
        route_id = thread_routes.get(candidate.path.stem)
        if route_id is not None:
            if ambiguous:
                rejected_all.add(route_id)
            else:
                rejected_after[route_id] = max(rejected_after.get(route_id, 0), modified_ns)
            return
        if ambiguous:
            unknown_rejected_all = True
        else:
            unknown_rejected_after = max(unknown_rejected_after or 0, modified_ns)

    for candidate in _iter_jsonl_files(roots, max_files):
        if remaining_bytes <= 0:
            reject(candidate)
            continue
        parsed, consumed = _parse_source(
            candidate.path,
            now=current,
            max_bytes=max_bytes,
            remaining_bytes=remaining_bytes,
            defer_future_validation=lifecycle_enabled,
        )
        remaining_bytes -= consumed
        if parsed is None:
            reject(candidate)
            continue
        if parsed["device"] != candidate.device or parsed["inode"] != candidate.inode:
            reject(candidate, replaced=True)
            continue
        identities = parsed.get("identities")
        if lifecycle_enabled:
            owner = parsed.get("owner")
            matched_routes = {thread_routes[owner]} if owner in thread_routes else set()
        else:
            matched_routes = {
                thread_routes[identity]
                for identity in identities if isinstance(identity, str) and identity in thread_routes
            } if isinstance(identities, set) else set()
        if len(matched_routes) != 1:
            continue
        route_id = next(iter(matched_routes))
        existing = observations.get(route_id)
        modified_ns = parsed["modified_ns"]
        if existing is None or modified_ns > existing[0]:
            observations[route_id] = (modified_ns, candidate.source, parsed)

    lifecycle = (
        _read_lifecycle_snapshot(Path(lifecycle_path), thread_routes=thread_routes)
        if lifecycle_enabled
        else None
    )
    if lifecycle_enabled:
        finished = time.monotonic()
        elapsed = finished - scan_started if scan_started is not None else 0.0
        if not isinstance(elapsed, (int, float)) or elapsed < 0 or elapsed != elapsed:
            elapsed = 0.0
        current += timedelta(seconds=elapsed)
        for _, _, parsed in observations.values():
            if not _matches_source_snapshot(parsed):
                parsed["invalid"] = True
            latest_timestamp = parsed.get("latest_timestamp")
            if isinstance(latest_timestamp, datetime) and latest_timestamp > current + MAX_FUTURE_SKEW:
                parsed["invalid"] = True

    for route_id, route in ((item[0], item) for item in ROUTE_CONTRACT):
        observation = observations.get(route_id)
        if observation is None:
            if lifecycle_enabled or route_id in rejected_all or route_id in rejected_after:
                agents[route_id]["freshness"] = "invalid"
            continue
        modified_ns, source, parsed = observation
        poisoned = (
            route_id in rejected_all
            or unknown_rejected_all
            or modified_ns <= rejected_after.get(route_id, -1)
            or (
                unknown_rejected_after is not None
                and modified_ns <= unknown_rejected_after
            )
        )
        if poisoned:
            agents[route_id]["freshness"] = "invalid"
            continue
        if lifecycle_enabled:
            agents[route_id] = _project_lifecycle_source(
                parsed,
                route=route,
                now=current,
                lifecycle=lifecycle.get(route_id) if lifecycle is not None else None,
            )
        else:
            agents[route_id] = _project_source(
                parsed,
                route=route,
                now=current,
                source=source,
                process_probe=process_probe,
            )
    return {
        "schema": SCHEMA,
        "observed_at": _iso(current),
        "route_registry_sha256": hashlib.sha256(raw_registry).hexdigest(),
        "agents": [agents[route_id] for route_id, *_ in ROUTE_CONTRACT],
    }


def validate_native_activity_checkpoint(
    checkpoint: object,
    *,
    now: datetime,
    max_age: timedelta = timedelta(minutes=30),
) -> dict[str, Any] | None:
    """Return a strictly allowlisted checkpoint, or ``None`` on any ambiguity."""
    if not isinstance(checkpoint, dict) or set(checkpoint) != {
        "schema", "observed_at", "route_registry_sha256", "agents"
    }:
        return None
    observed = _parse_time(checkpoint.get("observed_at"))
    current = _utc(now)
    if (
        checkpoint.get("schema") != SCHEMA
        or observed is None
        or observed > current
        or current - observed > max_age
        or not isinstance(checkpoint.get("route_registry_sha256"), str)
        or _SAFE_HASH.fullmatch(checkpoint["route_registry_sha256"]) is None
        or not isinstance(checkpoint.get("agents"), list)
        or len(checkpoint["agents"]) != len(ROUTE_CONTRACT)
    ):
        return None

    sanitized_agents: list[dict[str, Any]] = []
    for expected, raw in zip(ROUTE_CONTRACT, checkpoint["agents"]):
        if not isinstance(raw, dict) or set(raw) != set(PUBLIC_AGENT_FIELDS):
            return None
        route_id, project, department_id, agent_role = expected
        if (
            raw.get("route_id") != route_id
            or raw.get("project") != project
            or raw.get("department_id") != department_id
            or raw.get("agent_role") != agent_role
            or raw.get("state") not in {None, "running", "idle"}
            or raw.get("availability") not in {"available", "uncertain", "unavailable"}
            or raw.get("freshness") not in {"fresh", "stale", "unavailable", "invalid"}
            or raw.get("outcome_stage") not in {None, "turn_completed"}
        ):
            return None
        state_at = _parse_time(raw.get("state_at")) if raw.get("state_at") is not None else None
        if raw.get("state_at") is not None and (
            state_at is None or state_at > current or state_at > observed
        ):
            return None
        age = current - state_at if state_at is not None else None
        state = raw.get("state")
        availability = raw.get("availability")
        freshness = raw.get("freshness")
        outcome_stage = raw.get("outcome_stage")
        if freshness == "fresh" and (state_at is None or age is None):
            return None
        if freshness == "stale" and (state_at is None or age is None or age <= FRESH_FOR):
            return None
        if freshness in {"unavailable", "invalid"} and state_at is not None:
            return None
        if state == "running" and not (
            availability == "available"
            and freshness == "fresh"
            and state_at is not None
            and outcome_stage is None
        ):
            return None
        if state == "idle" and not (
            availability == "available"
            and freshness == "fresh"
            and state_at is not None
            and outcome_stage == "turn_completed"
        ):
            return None
        if state is None and (availability == "available" or outcome_stage is not None):
            return None
        if availability == "uncertain" and freshness != "fresh":
            return None
        if freshness in {"stale", "unavailable", "invalid"} and not (
            state is None and availability == "unavailable" and outcome_stage is None
        ):
            return None
        if freshness == "fresh" and age > FRESH_FOR:
            # A checkpoint may remain a valid envelope after its live proof
            # expires. Preserve the roster and timestamp, but never the old
            # execution/outcome claim.
            state = None
            availability = "unavailable"
            freshness = "stale"
            outcome_stage = None
        sanitized_agents.append({
            "route_id": route_id,
            "project": project,
            "department_id": department_id,
            "agent_role": agent_role,
            "state": state,
            "availability": availability,
            "freshness": freshness,
            "state_at": _iso(state_at) if state_at is not None else None,
            "outcome_stage": outcome_stage,
        })
    return {
        "schema": SCHEMA,
        "observed_at": _iso(observed),
        "route_registry_sha256": checkpoint["route_registry_sha256"],
        "agents": sanitized_agents,
    }


def default_native_roots() -> dict[str, list[Path]]:
    home = Path.home()
    return {
        "codex": [home / ".codex/sessions", home / ".codex/archived_sessions"],
        "claude": [home / ".claude/projects", home / ".config/claude/projects"],
    }
