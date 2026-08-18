"""ctypes declarations and shared-library discovery for ccobs."""

import ctypes
import ctypes.util
import os
import sys
from pathlib import Path
from typing import Optional


class State(ctypes.Structure):
    """Opaque ``ccobs_state``; allocate it through ``ccobs_create``."""


# Opaque state pointer to ccobs
StatePointer = ctypes.POINTER(State)

# Miscellaneous pointer types
BytePointer = ctypes.POINTER(ctypes.c_uint8)
SizePointer = ctypes.POINTER(ctypes.c_size_t)


def _library_names() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("ccobs.dll", "libccobs.dll")
    if sys.platform == "darwin":
        return ("libccobs.dylib", "ccobs.dylib")
    return ("libccobs.so",)


def _bundled_library_paths(package_dir: Path) -> list[str]:
    """Return platform library names produced by the setuptools build."""
    if sys.platform == "win32":
        patterns = ("_ccobs*.pyd", "_ccobs*.dll")
    elif sys.platform == "darwin":
        patterns = ("_ccobs*.so", "_ccobs*.dylib")
    else:
        patterns = ("_ccobs*.so",)

    return [str(path) for pattern in patterns for path in package_dir.glob(pattern)]


def _load_library(path: Optional[os.PathLike[str] | str] = None) -> ctypes.CDLL:
    candidates: list[str] = []
    explicit = path if path is not None else os.environ.get("CCOBS_LIBRARY_PATH")
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if explicit_path.is_dir():
            candidates.extend(str(explicit_path / name) for name in _library_names())
        else:
            candidates.append(str(explicit_path))

    package_dir = Path(__file__).resolve().parent
    candidates.extend(_bundled_library_paths(package_dir))
    candidates.extend(str(package_dir / name) for name in _library_names())
    discovered = ctypes.util.find_library("ccobs")
    if discovered:
        candidates.append(discovered)

    errors: list[str] = []
    for candidate in candidates:
        try:
            return ctypes.CDLL(candidate)
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")

    detail = "\n".join(errors) if errors else "no library candidates were found"
    raise OSError(
        "Unable to load the ccobs shared library. Install it where the platform "
        "loader can find it, or set CCOBS_LIBRARY_PATH to the library file or "
        f"its directory. Attempts:\n{detail}"
    )


def bind(path: Optional[os.PathLike[str] | str] = None) -> ctypes.CDLL:
    """Load ccobs and apply exact argument/result declarations to its C API."""

    lib = _load_library(path)

    # ccobs_create
    lib.ccobs_create.argtypes = [ctypes.POINTER(ctypes.c_int)]
    lib.ccobs_create.restype = StatePointer

    # ccobs_init
    lib.ccobs_init.argtypes = [StatePointer]
    lib.ccobs_init.restype = ctypes.c_int

    # ccobs_reset
    lib.ccobs_reset.argtypes = [StatePointer]
    lib.ccobs_reset.restype = ctypes.c_int

    # ccobs_destroy
    lib.ccobs_destroy.argtypes = [StatePointer]
    lib.ccobs_destroy.restype = None

    # ccobs_encode
    lib.ccobs_encode.argtypes = [
        StatePointer, BytePointer, SizePointer, BytePointer, SizePointer, ctypes.c_bool
    ]
    lib.ccobs_encode.restype = ctypes.c_int

    # ccobs_decode
    lib.ccobs_decode.argtypes = [
        StatePointer, BytePointer, SizePointer, BytePointer, SizePointer,
        ctypes.POINTER(ctypes.c_bool),
    ]
    lib.ccobs_decode.restype = ctypes.c_int

    # ccobs_encode_max_size
    lib.ccobs_encode_max_size.argtypes = [ctypes.c_size_t]
    lib.ccobs_encode_max_size.restype = ctypes.c_size_t

    # ccobs_encodev
    lib.ccobs_encodev.argtypes = [
        StatePointer, ctypes.POINTER(BytePointer), SizePointer, SizePointer,
        BytePointer, SizePointer,
    ]
    lib.ccobs_encodev.restype = ctypes.c_int

    # ccobs_decodev
    lib.ccobs_decodev.argtypes = [
        StatePointer, BytePointer, SizePointer, BytePointer, SizePointer,
        SizePointer, SizePointer,
    ]
    lib.ccobs_decodev.restype = ctypes.c_int

    # ccobs_error_string
    lib.ccobs_error_string.argtypes = [ctypes.c_int]
    lib.ccobs_error_string.restype = ctypes.c_char_p

    return lib
