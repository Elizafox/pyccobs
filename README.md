# pyccobs

`pyccobs` provides Python bindings to [ccobs](https://github.com/Elizafox/ccobs)
using only the standard library's `ctypes` module. The ccobs C library is
vendored and built into the package, so a separate ccobs installation is not
required. It includes one-shot and streaming APIs as well as exposing the
native library handle.

## Build and use

Python 3.11+ is required.

```sh
python -m pip install -e .
```

To cross-compile a Windows wheel on a system with MinGW-w64 installed, select
the target architecture through the PEP 517 build setting:

```sh
python -m build --wheel --config-setting=mingw=x86_64
```

The accepted targets are `x86_64` and `i686` (or their full MinGW triplets).
The compiler defaults to `<triplet>-gcc`; `CC`, `CFLAGS`, and `LDFLAGS` can
override or supplement the toolchain. Because the package uses `ctypes` rather
than the CPython extension API,
the resulting wheel is tagged for Python 3 generally (for example,
`py3-none-win_amd64`).

Set `CCOBS_LIBRARY_PATH` to a compatible shared library (or its directory) to
override the bundled copy when testing a different ccobs build.

```python
import ccobs

wire = ccobs.encode(b"hello\0world")
assert ccobs.decode(wire) == b"hello\0world"

batch = ccobs.encodev([b"first", b"", b"third"])
assert batch == b"".join(ccobs.encode(item) for item in [b"first", b"", b"third"])

encoder = ccobs.Encoder()
wire = encoder.feed(b"hello ") + encoder.feed(b"world", end_message=True)
encoder.close()

decoder = ccobs.Decoder()
first, used, complete = decoder.feed(wire)
decoder.close()
```

`Decoder.feed()` returns `(decoded_bytes, consumed_bytes, message_complete)`.
It stops at the first frame so the unconsumed suffix can be submitted again.
Both stateful classes are context managers and have `reset()` and `close()`.

For direct access to `ccobs_create`, `ccobs_encodev`, and the rest of the C API,
use `ccobs.load_library()`. Its functions have their ctypes `argtypes` and
`restype` declarations installed.
