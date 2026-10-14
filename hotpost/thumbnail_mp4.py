"""Keep H.264 reference samples while replacing the first presented frame.

FFmpeg concatenates a one-frame cover and the original compressed video. The
original first sample remains decoder preroll: P/B frames still need it. A
single edit list and composition offsets hide that sample without changing
any subsequent presentation times. This targets our CFR, non-fragmented MP4s.
"""
from __future__ import annotations

import struct
from pathlib import Path


def _boxes(data):
    pos = 0
    while pos < len(data):
        if len(data)-pos < 8:
            raise ValueError('잘린 MP4 메타데이터입니다.')
        size, kind = struct.unpack_from('>I4s', data, pos)
        header = 8
        if size == 1:
            if len(data)-pos < 16:
                raise ValueError('잘린 MP4 확장 헤더입니다.')
            size = struct.unpack_from('>Q', data, pos+8)[0]
            header = 16
        if size < header or pos+size > len(data):
            raise ValueError('올바르지 않은 MP4 상자 길이입니다.')
        yield kind, _box(kind, data[pos+header:pos+size])
        pos += size


def _box(kind, payload):
    return struct.pack('>I4s', len(payload)+8, kind)+payload


def _child(box, kind):
    matches = [b for t, b in _boxes(box[8:]) if t == kind]
    if len(matches) != 1:
        raise ValueError(f'MP4 {kind.decode()} 정보를 확인할 수 없습니다.')
    return matches[0]


def _roots(path):
    rows = []
    with Path(path).open('rb') as stream:
        length = stream.seek(0, 2)
        pos = 0
        while pos < length:
            stream.seek(pos)
            header = stream.read(8)
            if len(header) != 8:
                raise ValueError('잘린 MP4 파일입니다.')
            size, kind = struct.unpack('>I4s', header)
            head_size = 8
            if size == 1:
                extended = stream.read(8)
                if len(extended) != 8:
                    raise ValueError('잘린 MP4 확장 헤더입니다.')
                size = struct.unpack('>Q', extended)[0]
                head_size = 16
            elif size == 0:
                size = length-pos
            if size < head_size or pos+size > length or kind == b'moof':
                raise ValueError('지원하지 않는 MP4 구조입니다.')
            rows.append((kind, pos, size, head_size))
            pos += size
    return rows


def _moov(path):
    rows = _roots(path)
    candidates = [r for r in rows if r[0] == b'moov']
    if len(candidates) != 1 or candidates[0][2] > 64*1024*1024:
        raise ValueError('MP4 메타데이터 크기·구조를 확인할 수 없습니다.')
    kind, pos, size, header = candidates[0]
    with Path(path).open('rb') as stream:
        stream.seek(pos+header)
        return _box(kind, stream.read(size-header)), rows


def _video(moov):
    tracks = [b for t, b in _boxes(moov[8:]) if t == b'trak'
              and _child(_child(b, b'mdia'), b'hdlr')[16:20] == b'vide']
    if len(tracks) != 1:
        raise ValueError('한 개의 영상 트랙만 지원합니다.')
    return tracks[0]


def _expand(box, signed=False):
    if len(box) < 16:
        raise ValueError('잘린 MP4 타이밍 표입니다.')
    count = struct.unpack_from('>I', box, 12)[0]
    if len(box) != 16+8*count:
        raise ValueError('잘못된 MP4 타이밍 표입니다.')
    values = []
    for pos in range(16, len(box), 8):
        n, value = struct.unpack_from('>Ii' if signed else '>II', box, pos)
        if not n or len(values)+n > 216000:
            raise ValueError('썸네일 반영은 2시간 이내 영상에서 지원합니다.')
        values.extend([value]*n)
    return values


def _rle(kind, values, signed=False):
    rows = []
    for value in values:
        if rows and rows[-1][1] == value:
            rows[-1] = (rows[-1][0]+1, value)
        else:
            rows.append((1, value))
    return _box(kind, bytes([int(signed), 0, 0, 0])+struct.pack('>I', len(rows))+
                b''.join(struct.pack('>Ii' if signed else '>II', *r) for r in rows))


def video_timing(path):
    moov, _ = _moov(path)
    track = _video(moov)
    mdia = _child(track, b'mdia')
    mdhd = _child(mdia, b'mdhd')
    timescale = struct.unpack_from('>I', mdhd, 28 if mdhd[8] == 1 else 20)[0]
    table = _child(_child(mdia, b'minf'), b'stbl')
    deltas = _expand(_child(table, b'stts'))
    if timescale % 30 or not deltas or any(d != timescale//30 for d in deltas):
        raise ValueError('첫 프레임 교체는 일정한 30fps 영상에서 지원합니다.')
    elst = _child(_child(track, b'edts'), b'elst')
    if struct.unpack_from('>I', elst, 12)[0] != 1:
        raise ValueError('기존 영상의 시작 타이밍을 확인할 수 없습니다.')
    delay = struct.unpack_from('>q' if elst[8] == 1 else '>i', elst, 24 if elst[8] == 1 else 20)[0]
    rate = elst[32:36] if elst[8] == 1 else elst[24:28]
    if delay < 0 or rate != b'\x00\x01\x00\x00':
        raise ValueError('지원하지 않는 MP4 재생 속도입니다.')
    ctts = [b for t, b in _boxes(table[8:]) if t == b'ctts']
    offsets = _expand(ctts[0], ctts[0][8] == 1) if ctts else [0]*len(deltas)
    if len(offsets) != len(deltas) or offsets[0] != delay:
        raise ValueError('기존 첫 프레임의 타이밍을 확인할 수 없습니다.')
    return timescale, deltas, offsets, delay


def present_cover(joined, original, target):
    scale, deltas, offsets, old_delay = video_timing(original)
    moov, roots = _moov(joined)
    if roots[0][0] != b'ftyp' or roots[-1][0] != b'moov':
        raise ValueError('결합한 MP4의 배치를 확인할 수 없습니다.')
    joined_table = _child(_child(_child(_video(moov), b'mdia'), b'minf'), b'stbl')
    if len(_expand(_child(joined_table, b'stts'))) != len(deltas)+1:
        raise ValueError('결합한 영상의 프레임 수가 달라졌습니다.')
    delay = max(old_delay, scale//30)
    composition = [delay, 0]+[v+delay-old_delay for v in offsets[1:]]
    duration = sum(deltas)
    if duration > 0xffffffff or delay > 0x7fffffff:
        raise ValueError('MP4 타이밍 범위를 벗어났습니다.')

    def transform(parent, video=False, shift=0):
        parts = []
        has_ctts = False
        for kind, child in _boxes(parent[8:]):
            is_video = video
            if kind == b'trak':
                is_video = _child(_child(child, b'mdia'), b'hdlr')[16:20] == b'vide'
            if kind in (b'trak', b'mdia', b'minf', b'stbl', b'edts'):
                child = transform(child, is_video, shift)
            elif not shift and (kind == b'mvhd' or video and kind in (b'tkhd', b'mdhd')):
                # The joined movie and video track use the source video timescale.
                value = bytearray(child)
                field = (36 if kind == b'tkhd' else 32) if value[8] == 1 else (28 if kind == b'tkhd' else 24)
                struct.pack_into('>Q' if value[8] == 1 else '>I', value, field, duration)
                child = bytes(value)
            elif not shift and video and kind == b'elst':
                child = _box(kind, struct.pack('>IIIiHH', 0, 1, duration, delay, 1, 0))
            elif not shift and video and kind == b'stts':
                child = _rle(kind, [0]+deltas)
            elif video and kind == b'ctts':
                has_ctts = True
                if not shift:
                    child = _rle(kind, composition, min(composition) < 0)
            elif not shift and video and kind == b'stss':
                sync = [struct.unpack_from('>I', child, p)[0] for p in range(16, len(child), 4)]
                # A hidden reference frame must not be a public seek target.
                sync = [n for n in sync if n != 2]
                child = _box(kind, child[8:12]+struct.pack('>I', len(sync))+
                             b''.join(struct.pack('>I', n) for n in sync))
            elif shift and kind in (b'stco', b'co64'):
                width, fmt = (4, '>I') if kind == b'stco' else (8, '>Q')
                count = struct.unpack_from('>I', child, 12)[0]
                if len(child) != 16+count*width:
                    raise ValueError('잘못된 MP4 청크 표입니다.')
                child = _box(kind, child[8:16]+b''.join(struct.pack(fmt, struct.unpack_from(fmt, child, p)[0]+shift)
                    for p in range(16, len(child), width)))
            parts.append(child)
        if not shift and video and parent[4:8] == b'stbl' and not has_ctts:
            parts.append(_rle(b'ctts', composition, min(composition) < 0))
        return _box(parent[4:8], b''.join(parts))

    revised = transform(moov)
    revised = transform(revised, shift=len(revised))
    # Place moov before media for browser startup and range seeking; media bytes
    # stay untouched. The joined file has its old moov at the end.
    with Path(joined).open('rb') as source, Path(target).open('wb') as output:
        for index, (kind, pos, size, _) in enumerate(roots):
            if kind == b'moov':
                continue
            source.seek(pos)
            remaining = size
            while remaining:
                chunk = source.read(min(1024*1024, remaining))
                if not chunk:
                    raise ValueError('잘린 MP4 미디어입니다.')
                output.write(chunk)
                remaining -= len(chunk)
            if index == 0:
                output.write(revised)
