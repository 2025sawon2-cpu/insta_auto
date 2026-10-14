import pytest
from hotpost.youtube_ump import BrowserUmpMedia, ump_integer


def uint(value):
    if value < 128:
        return bytes([value])
    if value < 16384:
        return bytes([128 | (value & 63), value >> 6])
    return b'\xf0' + value.to_bytes(4, 'little')


def proto_uint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result) + bytes([value])


def field(key, value):
    if isinstance(value, bytes):
        return proto_uint(key << 3 | 2) + proto_uint(len(value)) + value
    return proto_uint(key << 3) + proto_uint(value)


def part(kind, data):
    return uint(kind) + uint(len(data)) + data


def segment(payload=b'abc', start=0, version=1, video=b'wanted', length=None, end=True, compression=0):
    header = b''.join(field(k, v) for k, v in [(1, 0), (2, video), (3, 398), (4, version),
                                               (6, start), (7, compression), (14, len(payload) if length is None else length)])
    value = part(20, header) + part(21, b'\x00' + payload)
    return value + part(22, b'\x00') if end else value


def test_complete_segments_can_arrive_out_of_order_and_duplicates_do_not_repeat():
    media = BrowserUmpMedia('wanted')
    media.add(segment(b'def', 3)); media.add(segment(b'abc')); media.add(segment(b'abc'))
    assert media.contiguous_tracks()[0]['body'] == b'abcdef'
    assert media.received_bytes == 6


def test_prefetched_other_video_is_excluded_even_with_same_duration_and_format():
    media = BrowserUmpMedia('wanted')
    media.add(segment(video=b'other')); media.add(segment())
    assert media.ignored_other_video_headers == 1
    assert media.contiguous_tracks()[0]['body'] == b'abc'


def test_format_versions_and_byte_gaps_remain_separate():
    media = BrowserUmpMedia('wanted')
    media.add(segment()); media.add(segment(b'ghi', 6)); media.add(segment(b'xyz', version=2))
    tracks = media.contiguous_tracks()
    assert len(tracks) == 2
    assert tracks[0]['body'] == b'abc' and not tracks[0]['gap_free']
    assert tracks[1]['body'] == b'xyz'


@pytest.mark.parametrize('body', [segment(length=4), segment(end=False), segment()[:-1],
                                segment(compression=1), part(12, b'ciphertext')])
def test_incomplete_compressed_or_encrypted_media_is_never_accepted(body):
    media = BrowserUmpMedia('wanted')
    with pytest.raises(ValueError):
        media.add(body)
    assert media.contiguous_tracks() == []


def test_conflicting_overlap_and_bounded_allocation_fail():
    media = BrowserUmpMedia('wanted')
    media.add(segment())
    with pytest.raises(ValueError, match='Conflicting'):
        media.add(segment(b'XX', 1))
    with pytest.raises(ValueError):
        BrowserUmpMedia('wanted', max_bytes=2).add(segment())


def test_ump_integer_sizes_and_incomplete_prefix():
    assert ump_integer(b'\x7f', 0) == (127, 1)
    assert ump_integer(b'\x80\x02', 0) == (128, 2)
    assert ump_integer(b'\xc0\x00\x01', 0) == (8192, 3)
    assert ump_integer(b'\xe0\x00\x00\x01', 0) == (1048576, 4)
    assert ump_integer(b'\xf0\x01\x00\x00\x00', 0) == (1, 5)
    with pytest.raises(ValueError):
        ump_integer(b'\xf0\x01', 0)
