"""Resumable SHA-256 with the legacy Hub database state format."""
import struct

from sha256 import sha256


class ResumableSHA256:
    # OpenSSL 1.1's SHA256_CTX on the supported little-endian x86-64 hosts,
    # followed by the eight unused bytes saved by the old EVP implementation.
    _state = struct.Struct('<8I2I64sII8x')
    _words = struct.Struct('>8I')
    __slots__ = ('_hasher', '_buffer', '_state_bytes')

    def __init__(self, state=None):
        self._hasher = sha256()
        self._buffer = b''
        self._state_bytes = None
        if state is not None:
            if len(state) != self._state.size:
                raise ValueError(f'invalid sha256 digester state, got {len(state)} bytes')
            *words, low, high, buffer, pending, digest_size = self._state.unpack(state)
            bits = (high << 32) | low
            if digest_size != 32 or pending >= 64 or bits % 8 or (bits // 8) % 64 != pending:
                raise ValueError('invalid sha256 digester state fields')
            self._hasher.state = (self._words.pack(*words), bits // 8 - pending)
            self._buffer = buffer[:pending]
            # Revertable database deletes compare the serialized value byte
            # for byte, including unused bytes left in old OpenSSL buffers.
            self._state_bytes = bytes(state)

    def get_state(self):
        if self._state_bytes is not None:
            return self._state_bytes
        words, count = self._hasher.state
        bits = (count + len(self._buffer)) * 8
        return self._state.pack(
            *self._words.unpack(words), bits & 0xffffffff, bits >> 32,
            self._buffer, len(self._buffer), 32
        )

    def __copy__(self):
        return ResumableSHA256(self.get_state())

    def update(self, data):
        if not data:
            return
        self._state_bytes = None
        data = self._buffer + data
        complete = len(data) - len(data) % 64
        # Bound the native implementation's internal buffer copies when a
        # large address history is rebuilt in one update.
        for offset in range(0, complete, 4096):
            self._hasher.update(data[offset:min(offset + 4096, complete)])
        self._buffer = data[complete:]

    def digest(self):
        # The dependency's digest() finalizes its state. Keep hashlib's
        # non-destructive behavior for callers that continue updating.
        hasher = sha256()
        hasher.state = self._hasher.state
        hasher.update(self._buffer)
        return hasher.digest()
