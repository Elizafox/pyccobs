# pyccobs

`pyccobs` provides Python bindings to [ccobs](https://github.com/Elizafox/ccobs)
using only the standard library's `ctypes` module. The ccobs C library is
vendored and built into the package, so a separate ccobs installation is not
required. It includes one-shot and streaming APIs as well as exposing the
native library handle.

## Build and use

Python 3.11+ and CMake 3.15+ are required.

```sh
python -m pip install -e .
```

The package build invokes the vendored ccobs CMake project directly. Because
the package uses `ctypes` rather than the CPython extension API, the resulting
wheel is tagged for Python 3 generally (for example, `py3-none-win_amd64`).

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
wire += encoder.feedv([b"second", b"third"])
encoder.close()

decoder = ccobs.Decoder()
decoded, used, frame_sizes = decoder.feedv(wire)
decoder.close()
```

`Decoder.feed()` returns `(decoded_bytes, consumed_bytes, message_complete)`
and stops after the first complete frame. `Decoder.feedv()` returns
`(decoded_bytes, consumed_bytes, frame_sizes)` and
decodes every complete frame in the supplied chunk in one `ccobs_decodev()`
call. `frame_sizes` gives the decoded size of each completed frame in the flat
output; a size may include bytes returned by an earlier partial call.
`Encoder.feedv()` encodes a batch of complete messages through the native
streaming vector API. Both stateful classes are context managers and have
`reset()` and `close()`.

For direct access to `ccobs_create`, `ccobs_encodev`, and the rest of the C API,
use `ccobs.load_library()`. Its functions have their ctypes `argtypes` and
`restype` declarations installed.
