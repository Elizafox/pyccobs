"""Pythonic ctypes bindings for the ccobs C library."""

import ctypes
import os
from collections.abc import Iterable
from enum import IntEnum
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
    """Incrementally encode message chunks or batches of complete messages."""

    _OUTPUT_CHUNK_SIZE = 64 * 1024

    def feed(self, data: object = b"", *, end_message: bool = False) -> bytes:
        raw = memoryview(data).cast("B").tobytes()
        if end_message:
            return self.feedv((raw,))

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

    def feedv(self, messages: Iterable[object]) -> bytes:
        """Encode complete, independent messages into one flat framed stream.

        The encoder state is retained between calls. If :meth:`feed` previously
        supplied an unfinished message, the first message completes it.
        """
        pending = [memoryview(message).cast("B").tobytes() for message in messages]
        if not pending:
            return b""

        offsets = [0] * len(pending)
        result = bytearray()
        while pending:
            count = len(pending)
            owners: list[object | None] = []
            pointers = (BytePointer * count)()
            sizes = (ctypes.c_size_t * count)()
            maximum = 0
            for index, raw in enumerate(pending):
                owner, pointer = _input_buffer(raw)
                owners.append(owner)
                offset = offsets[index]
                pointers[index] = (
                    ctypes.cast(ctypes.byref(owner, offset), BytePointer)
                    if owner
                    else pointer
                )
                sizes[index] = len(raw) - offset
                maximum += int(self._lib.ccobs_encode_max_size(sizes[index]))

            capacity = max(257, min(maximum, self._OUTPUT_CHUNK_SIZE))
            output = (ctypes.c_uint8 * capacity)()
            completed = ctypes.c_size_t(count)
            written = ctypes.c_size_t(capacity)
            code = self._lib.ccobs_encodev(
                self._state,
                pointers,
                sizes,
                ctypes.byref(completed),
                output,
                ctypes.byref(written),
            )
            result.extend(output[: written.value])

            for index in range(min(completed.value + 1, count)):
                offsets[index] += sizes[index]
            if completed.value:
                del pending[: completed.value]
                del offsets[: completed.value]

            if code == Error.NEED_OUTPUT:
                continue
            if code != Error.OK:
                _raise_error(self._lib, code)
            if completed.value != count:
                raise CcobsError(
                    Error.PARTIAL, "ccobs_encodev did not complete the batch"
                )

        return bytes(result)


class Decoder(_State):
    """Incrementally decode framed stream chunks."""

    def feed(self, data: object = b"") -> tuple[bytes, int, bool]:
        """Decode at most one frame and report whether it was completed."""
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

    def feedv(self, data: object = b"") -> tuple[bytes, int, tuple[int, ...]]:
        """Decode framed stream data into one flat byte string.

        The decoder state is retained between calls. The returned tuple contains
        the decoded bytes, consumed input byte count, and completed frame sizes.
        If a frame began in a previous call, its size includes bytes returned by
        that call.
        """
        raw = memoryview(data).cast("B").tobytes()
        owner, _ = _input_buffer(raw)
        output_capacity = max(1, len(raw))
        output = (ctypes.c_uint8 * output_capacity)()
        available = ctypes.c_size_t(len(raw))
        written = ctypes.c_size_t(output_capacity)

        # Every complete encoded frame ends in zero.  The extra slot lets
        # decodev consume a partial frame following the final delimiter.
        frame_capacity = raw.count(0) + 1
        frame_sizes = (ctypes.c_size_t * frame_capacity)()
        frame_count = ctypes.c_size_t(frame_capacity)
        code = self._lib.ccobs_decodev(
            self._state,
            ctypes.cast(owner, BytePointer) if owner else BytePointer(),
            ctypes.byref(available),
            output,
            ctypes.byref(written),
            frame_sizes,
            ctypes.byref(frame_count),
        )
        if code not in (Error.OK, Error.PARTIAL):
            _raise_error(self._lib, code)

        sizes = tuple(frame_sizes[: frame_count.value])
        return bytes(output[: written.value]), available.value, sizes


def encode(data: object, *, library: Optional[ctypes.CDLL] = None) -> bytes:
    """Encode one bytes-like message, including its trailing zero delimiter."""
    with Encoder(library) as encoder:
        return encoder.feed(data, end_message=True)


def encodev(
    messages: Iterable[object], *, library: Optional[ctypes.CDLL] = None
) -> bytes:
    """Encode a batch of bytes-like messages into one flat framed stream."""
    with Encoder(library) as encoder:
        return encoder.feedv(messages)


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
