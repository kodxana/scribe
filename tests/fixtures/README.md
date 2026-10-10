# Resumable SHA-256 fixtures

These states were captured from Hub commit
`9f871d83c1a8e030148fb754c143998085c93240` using CPython 3.9 on
Debian Bullseye x86-64 (OpenSSL 1.1). The original implementation reads
OpenSSL's hash context through `rehash==1.0.0`.

`sha256-legacy.json` contains messages generated as
`bytes(i % 251 for i in range(length))`, their saved states and digests,
and the digest after appending `b' continuation'`. The lengths cover
block and padding boundaries. The 120-byte serialized values are database
fixtures, including unused buffer bytes; do not regenerate them with the
replacement implementation.

`sha256-counter.json` exercises the two 32-bit bit-count fields without
hashing gigabytes during every test. Starting with the legacy state after
`b'x' * 32`, its bit count is set to `byte_count * 8` with
`struct.pack_into('<II', state, 32, bits & 0xffffffff, bits >> 32)`.
The old implementation then produces both digests and the state after
appending `b'y' * 64`. These are synthetic intermediate states, not hashes
of messages of the stated length.
