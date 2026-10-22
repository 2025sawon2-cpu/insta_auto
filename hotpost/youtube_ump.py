"""Decode bounded clear UMP bodies actually received by the browser.

No requests, tokens, URL derivation, encrypted media, or authentication handling.
Format references: LuanRT/googlevideo MediaHeader and UmpReader, MIT project.
"""
from __future__ import annotations


def ump_integer(data, offset):
    if offset >= len(data):
        raise ValueError('Incomplete UMP integer.')
    prefix = data[offset]
    count = 1 if prefix < 128 else 2 if prefix < 192 else 3 if prefix < 224 else 4 if prefix < 240 else 5
    if offset + count > len(data):
        raise ValueError('Incomplete UMP integer.')
    if count == 5:
        return int.from_bytes(data[offset+1:offset+5], 'little'), offset+5
    shift = 8-count
    result = prefix & ((1 << shift)-1)
    for i in range(1, count):
        result |= data[offset+i] << shift
        shift += 8
    return result, offset+count


def protobuf_integer(data, offset):
    result = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            break
        byte = data[offset]
        offset += 1
        result |= (byte & 127) << shift
        if byte < 128:
            return result, offset
    raise ValueError('Incomplete/oversized protobuf integer.')


def media_header(data):
    result, offset = {}, 0
    while offset < len(data):
        tag, offset = protobuf_integer(data, offset)
        field, wire = tag >> 3, tag & 7
        if not field:
            raise ValueError('Invalid protobuf field.')
        if wire == 0:
            value, offset = protobuf_integer(data, offset)
        elif wire in (1, 2, 5):
            size, offset = protobuf_integer(data, offset) if wire == 2 else (8 if wire == 1 else 4, offset)
            if offset + size > len(data):
                raise ValueError('Incomplete protobuf payload.')
            value = data[offset:offset+size]
            offset += size
        else:
            raise ValueError('Unsupported protobuf wire type.')
        result[field] = value
    return result


class BrowserUmpMedia:
    """Keep only exact video-ID, format-version, complete clear segments."""
    def __init__(self, video_id, max_bytes=80*1024*1024):
        self.video_id, self.max_bytes = video_id, max_bytes
        self.tracks = {}
        self.ignored_other_video_headers = 0
        self.received_bytes = 0

    def add(self, body):
        if len(body) > self.max_bytes:
            raise ValueError('UMP body exceeds byte limit.')
        offset, pending, completed = 0, {}, []
        while offset < len(body):
            kind, offset = ump_integer(body, offset)
            size, offset = ump_integer(body, offset)
            if size > self.max_bytes or offset + size > len(body):
                raise ValueError('Incomplete/oversized UMP part.')
            part = body[offset:offset+size]
            offset += size
            if kind == 12:
                raise ValueError('Encrypted media is unsupported; stop.')
            if kind == 20:
                header = media_header(part)
                identifier = header.get(1)
                if identifier is None or identifier in pending:
                    raise ValueError('Missing/reused media header ID.')
                video = header.get(2, b'').decode('utf-8', 'strict')
                if video != self.video_id:
                    self.ignored_other_video_headers += 1
                    pending[identifier] = None
                    continue
                if header.get(7, 0) != 0:
                    raise ValueError('Compressed media is unsupported; stop.')
                if any(field not in header for field in (3, 4, 14)):
                    raise ValueError('Missing segment identity or bounds.')
                length = header[14]
                if not 0 < length <= self.max_bytes:
                    raise ValueError('Invalid segment length.')
                if header.get(17, 0) or header.get(18, length) != length:
                    raise ValueError('Partial segment requires more evidence; stop.')
                pending[identifier] = (header, bytearray())
            elif kind in (21, 22):
                identifier, position = ump_integer(part, 0)
                if identifier not in pending:
                    raise ValueError('Media has no matching header.')
                segment = pending[identifier]
                if kind == 21 and segment is not None:
                    header, payload = segment
                    if len(payload) + len(part) - position > header[14]:
                        raise ValueError('Media exceeds declared segment length.')
                    payload.extend(part[position:])
                if kind == 22:
                    if position != len(part):
                        raise ValueError('Unexpected media-end payload.')
                    if segment is not None:
                        header, payload = segment
                        if len(payload) != header[14]:
                            raise ValueError('Incomplete media segment.')
                        key = (header[3], header[4], header.get(13, b''))
                        completed.append((key, header.get(6, 0), bytes(payload)))
                    del pending[identifier]
        if pending:
            raise ValueError('Missing media-end part.')
        # Check the whole response before accepting its segments.
        for key, start, payload in completed:
            track = self.tracks.setdefault(key, {})
            for previous_start, previous in track.items():
                left, right = max(start, previous_start), min(start+len(payload), previous_start+len(previous))
                if left < right and payload[left-start:right-start] != previous[left-previous_start:right-previous_start]:
                    raise ValueError('Conflicting overlapping media bytes.')
            if start in track and track[start] == payload:
                continue
            if start < 0 or start + len(payload) > self.max_bytes or self.received_bytes + len(payload) > self.max_bytes:
                raise ValueError('Assembled media exceeds byte limit.')
            track[start] = payload
            self.received_bytes += len(payload)

    def contiguous_tracks(self):
        result = []
        for (itag, version, _), spans in self.tracks.items():
            output = bytearray()
            for start, payload in sorted(spans.items()):
                if start > len(output):
                    break
                overlap = len(output)-start
                if overlap < len(payload):
                    output.extend(payload[overlap:])
            if output:
                result.append({'itag': itag, 'version': version, 'body': bytes(output),
                               'gap_free': len(output) == max(start+len(payload) for start, payload in spans.items()),
                               'segments': len(spans)})
        return result
