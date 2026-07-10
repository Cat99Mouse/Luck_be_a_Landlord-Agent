"""Minimal Godot 3 PCK parser and writer.

This is intentionally narrow: it targets the Godot 3.x PCK format used by
Luck be a Landlord. It preserves file order and rewrites offsets when packing.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path


HEADER_PREFIX_SIZE = 4 + 4 + 4 + 4 + 4 + (16 * 4)
ENTRY_TAIL_SIZE = 8 + 8 + 16


@dataclass(frozen=True)
class PckEntry:
    """Single file entry in a Godot PCK."""

    path: str
    offset: int
    size: int
    md5: bytes


class GodotPck:
    """Read and rebuild a Godot 3 PCK."""

    def __init__(
        self,
        path: Path,
        pack_format: int,
        godot_version: tuple[int, int, int],
        entries: list[PckEntry],
        files: dict[str, bytes],
    ) -> None:
        self.path = path
        self.pack_format = pack_format
        self.godot_version = godot_version
        self.entries = entries
        self.files = files

    @classmethod
    def read(cls, path: str | Path) -> "GodotPck":
        """Read a Godot PCK into memory."""
        p = Path(path)
        data = p.read_bytes()
        if data[:4] != b"GDPC":
            raise ValueError(f"Not a Godot PCK: {p}")

        pack_format, major, minor, patch = struct.unpack_from("<IIII", data, 4)
        file_count = struct.unpack_from("<I", data, HEADER_PREFIX_SIZE)[0]
        cursor = HEADER_PREFIX_SIZE + 4

        entries: list[PckEntry] = []
        files: dict[str, bytes] = {}
        for _ in range(file_count):
            name_len = struct.unpack_from("<I", data, cursor)[0]
            cursor += 4
            raw_name = data[cursor : cursor + name_len]
            cursor += name_len
            name = raw_name.rstrip(b"\x00").decode("utf-8")
            offset, size = struct.unpack_from("<QQ", data, cursor)
            cursor += 16
            md5 = data[cursor : cursor + 16]
            cursor += 16
            entries.append(PckEntry(path=name, offset=offset, size=size, md5=md5))
            files[name] = data[offset : offset + size]

        return cls(
            path=p,
            pack_format=pack_format,
            godot_version=(major, minor, patch),
            entries=entries,
            files=files,
        )

    def get_text(self, path: str, encoding: str = "utf-8") -> str:
        """Return a packed file decoded as text."""
        return self.files[path].decode(encoding)

    def replace_text(self, path: str, text: str, encoding: str = "utf-8") -> None:
        """Replace a packed text file."""
        if path not in self.files:
            raise KeyError(path)
        self.files[path] = text.encode(encoding)

    def write(self, path: str | Path) -> None:
        """Write a rebuilt PCK."""
        out = Path(path)
        file_count = len(self.entries)
        index_size = HEADER_PREFIX_SIZE + 4
        encoded_names: dict[str, bytes] = {}
        for entry in self.entries:
            name = entry.path.encode("utf-8") + b"\x00"
            encoded_names[entry.path] = name
            index_size += 4 + len(name) + ENTRY_TAIL_SIZE

        offsets: dict[str, int] = {}
        cursor = index_size
        for entry in self.entries:
            offsets[entry.path] = cursor
            cursor += len(self.files[entry.path])

        chunks: list[bytes] = []
        chunks.append(b"GDPC")
        chunks.append(
            struct.pack(
                "<IIII",
                self.pack_format,
                self.godot_version[0],
                self.godot_version[1],
                self.godot_version[2],
            )
        )
        chunks.append(bytes(16 * 4))
        chunks.append(struct.pack("<I", file_count))

        for entry in self.entries:
            name = encoded_names[entry.path]
            payload = self.files[entry.path]
            chunks.append(struct.pack("<I", len(name)))
            chunks.append(name)
            chunks.append(struct.pack("<QQ", offsets[entry.path], len(payload)))
            chunks.append(hashlib.md5(payload).digest())

        for entry in self.entries:
            chunks.append(self.files[entry.path])

        out.write_bytes(b"".join(chunks))

