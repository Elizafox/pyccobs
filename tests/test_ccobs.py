import ctypes

import pytest

import ccobs


def test_known_vector():
    encoded = ccobs.encode(b"\x11\x22\x00\x33")
    assert encoded == b"\x03\x11\x22\x02\x33\x00"
    assert ccobs.decode(encoded) == b"\x11\x22\x00\x33"


@pytest.mark.parametrize("size", [0, 1, 253, 254, 255, 1024])
def test_round_trip_boundaries(size):
    original = bytes((index * 73) & 0xFF for index in range(size))
    assert ccobs.decode(ccobs.encode(original)) == original


def test_streaming_and_multiple_frames():
    with ccobs.Encoder() as encoder:
        wire = encoder.feed(b"abc")
        wire += encoder.feed(b"\x00def", end_message=True)
        wire += encoder.feed(b"second", end_message=True)

    with ccobs.Decoder() as decoder:
        first, used, complete = decoder.feed(wire)
        assert (first, complete) == (b"abc\x00def", True)
        second, used_again, complete = decoder.feed(wire[used:])
        assert (second, used_again, complete) == (b"second", len(wire) - used, True)


def test_encodev_batch():
    messages = [b"first", b"", b"third\x00message"]
    wire = ccobs.encodev(message for message in messages)
    assert wire == b"".join(ccobs.encode(message) for message in messages)


def test_encodev_empty_batch():
    assert ccobs.encodev([]) == b""


def test_partial_decoder():
    wire = ccobs.encode(b"hello")
    with ccobs.Decoder() as decoder:
        beginning, used, complete = decoder.feed(wire[:2])
        assert used == 2 and not complete
        ending, used, complete = decoder.feed(wire[2:])
        assert beginning + ending == b"hello"
        assert used == len(wire) - 2 and complete


def test_malformed_and_one_shot_validation():
    with pytest.raises(ccobs.MalformedInputError):
        ccobs.decode(b"\x02\x00")
    with pytest.raises(ValueError, match="incomplete"):
        ccobs.decode(b"\x02x")
    with pytest.raises(ValueError, match="after"):
        ccobs.decode(ccobs.encode(b"a") + ccobs.encode(b"b"))


def test_native_vector_symbols_are_typed():
    native = ccobs.load_library()
    assert native.ccobs_encodev.restype is ctypes.c_int
    assert native.ccobs_decodev.restype is ctypes.c_int
