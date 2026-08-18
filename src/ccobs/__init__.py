"""Pythonic ctypes bindings for the ccobs C library."""

from collections.abc import Iterable
import ctypes
from enum import IntEnum
import os
from typing import Optional

from ._lib import BytePointer, StatePointer, bind

__all__ = [
    "Decoder",
    "Encoder",
    "Error",
    "MalformedInputError",
    "CcobsError",
    "decode",
    "encode",
    "encodev",
    "load_library",
]


class Error(IntEnum):
    OK = 0
    PARTIAL = 1
    NEED_OUTPUT = 2
    NULL_ARGUMENT = 3
    MALFORMED_INPUT = 4
    OOM = 5


class CcobsError(Exception):
    """An error reported by the native ccobs library."""

    def __init__(self, code: int, message: str):
        self.code = Error(code) if code in Error._value2member_map_ else code
        super().__init__(message)


class MalformedInputError(CcobsError):
    """The encoded stream contains a malformed COBS frame."""


_library: Optional[ctypes.CDLL] = None


def load_library(path: Optional[os.PathLike[str] | str] = None) -> ctypes.CDLL:
    """Load and return ccobs, optionally from an explicit path.

    Calling this with a path replaces the process-wide library used by new
    encoders and decoders. Existing objects retain their original library.
    """
    global _library
    if path is not None or _library is None:
        _library = bind(path)
    return _library


def _message(lib: ctypes.CDLL, code: int) -> str:
    value = lib.ccobs_error_string(code)
    return value.decode("utf-8", "replace") if value else f"ccobs error {code}"


def _raise_error(lib: ctypes.CDLL, code: int) -> None:
    """Wrapper to turn ccobs error into idiomatic Python errors."""
    cls = MalformedInputError if code == Error.MALFORMED_INPUT else CcobsError
    raise cls(code, _message(lib, code))


def _input_buffer(data: bytes) -> tuple[object | None, BytePointer]:
    if not data:
        return None, BytePointer()
    owner = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
    return owner, ctypes.cast(owner, BytePointer)


class _State:
    """Wrapper to internal ccobs state."""

    def __init__(self, library: Optional[ctypes.CDLL] = None):
        self._lib = library or load_library()
        error = ctypes.c_int(Error.OK)
        self._state: StatePointer = self._lib.ccobs_create(ctypes.byref(error))
        if not self._state:
            _raise_error(self._lib, error.value)

    def close(self) -> None:
        state = getattr(self, "_state", None)
        if state:
            self._lib.ccobs_destroy(state)
            self._state = StatePointer()

    def reset(self) -> None:
        code = self._lib.ccobs_reset(self._state)
        if code != Error.OK:
            _raise_error(self._lib, code)

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __del__(self):
        self.close()


class Encoder(_State):
    """Incrementally encode one message at a time."""

    def feed(self, data: object = b"", *, end_message: bool = False) -> bytes:
        raw = memoryview(data).cast("B").tobytes()
        owner, _ = _input_buffer(raw)
        offset = 0
        result = bytearray()
        # 257 also drains a full native block retained from an earlier call.
        capacity = max(257, int(self._lib.ccobs_encode_max_size(len(raw))))
        while True:
            output = (ctypes.c_uint8 * capacity)()
            available = ctypes.c_size_t(len(raw) - offset)
            size = ctypes.c_size_t(capacity)
            current = (
                ctypes.cast(ctypes.byref(owner, offset), BytePointer)
                if owner
                else BytePointer()
            )
            code = self._lib.ccobs_encode(
                self._state,
                current,
                ctypes.byref(available),
                output,
                ctypes.byref(size),
                end_message,
            )
            offset += available.value
            result.extend(output[: size.value])

            if code == Error.NEED_OUTPUT:
                continue
            if code not in (Error.OK, Error.PARTIAL):
                _raise_error(self._lib, code)

            return bytes(result)


class Decoder(_State):
    """Incrementally decode a stream, stopping after its first complete frame."""

    def feed(self, data: object = b"") -> tuple[bytes, int, bool]:
        raw = memoryview(data).cast("B").tobytes()
        owner, _ = _input_buffer(raw)
        offset = 0
        result = bytearray()
        complete = ctypes.c_bool(False)
        capacity = max(1, len(raw))
        while True:
            output = (ctypes.c_uint8 * capacity)()
            available = ctypes.c_size_t(len(raw) - offset)
            size = ctypes.c_size_t(capacity)
            current = (
                ctypes.cast(ctypes.byref(owner, offset), BytePointer)
                if owner
                else BytePointer()
            )
            code = self._lib.ccobs_decode(
                self._state,
                current,
                ctypes.byref(available),
                output,
                ctypes.byref(size),
                ctypes.byref(complete),
            )
            offset += available.value
            result.extend(output[: size.value])
            if code == Error.NEED_OUTPUT:
                continue
            if code not in (Error.OK, Error.PARTIAL):
                _raise_error(self._lib, code)

            return bytes(result), offset, complete.value


def encode(data: object, *, library: Optional[ctypes.CDLL] = None) -> bytes:
    """Encode one bytes-like message, including its trailing zero delimiter."""
    with Encoder(library) as encoder:
        return encoder.feed(data, end_message=True)


def encodev(
    messages: Iterable[object], *, library: Optional[ctypes.CDLL] = None
) -> bytes:
    """Encode a batch of bytes-like messages into one flat framed stream."""
    lib = library or load_library()
    raw_messages = [memoryview(message).cast("B").tobytes() for message in messages]
    count = len(raw_messages)
    if count == 0:
        return b""

    owners: list[object | None] = []
    pointers = (BytePointer * count)()
    sizes = (ctypes.c_size_t * count)()
    capacity = 0
    for index, raw in enumerate(raw_messages):
        owner, pointer = _input_buffer(raw)
        owners.append(owner)
        pointers[index] = pointer
        sizes[index] = len(raw)
        capacity += int(lib.ccobs_encode_max_size(len(raw)))

    output = (ctypes.c_uint8 * capacity)()
    completed = ctypes.c_size_t(count)
    written = ctypes.c_size_t(capacity)
    with _State(lib) as state:
        code = lib.ccobs_encodev(
            state._state,
            pointers,
            sizes,
            ctypes.byref(completed),
            output,
            ctypes.byref(written),
        )

    if code != Error.OK:
        _raise_error(lib, code)
    if completed.value != count:
        raise CcobsError(Error.PARTIAL, "ccobs_encodev did not complete the batch")

    return bytes(output[: written.value])


def decode(data: object, *, library: Optional[ctypes.CDLL] = None) -> bytes:
    """Decode exactly one complete, zero-delimited frame."""
    raw = memoryview(data).cast("B").tobytes()
    with Decoder(library) as decoder:
        output, consumed, complete = decoder.feed(raw)
    if not complete:
        raise ValueError("incomplete COBS frame")
    if consumed != len(raw):
        raise ValueError("input contains data after the first COBS frame")

    return output
