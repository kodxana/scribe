# Protocol schemas

The SDK and Hub use protobuf 7.36.2. Generated modules are checked in so normal
installations do not need a protocol compiler. Do not edit generated `_pb2.py`
files by hand.

## Regeneration

From the repository root, create a separate Python 3.13 environment, install
`hub/schema/requirements.txt`, and run:

```sh
python scripts/regenerate_schema.py
python scripts/regenerate_schema.py --check
```

The script requires the pinned `grpcio-tools==1.84.0` compiler (libprotoc 35.1)
and protobuf runtime. It generates into a temporary directory, then adjusts
Python imports and module names for this package. CI checks that the committed
modules match these inputs. Existing JSON schemas are left intact.

## Source and wire compatibility

`proto/v1` and most of `proto/v2` come from
[lbryio/types at 73610f6654a62337c8edede48118e83bcb38aadf](https://github.com/lbryio/types/tree/73610f6654a62337c8edede48118e83bcb38aadf).
`result.proto` preserves the deployed SDK/Hub schema: field 22 is the double
`trending_score`, and the existing Go package option is retained. The upstream
file has a different type at that field number and must not replace it.

The Hub's additional `hub.proto` is recovered from its existing generated
descriptor because the corresponding source was not present upstream. Its
messages and RPC signatures are checked against the captured descriptor.

The compatibility fixtures under `tests/fixtures` were captured before
regeneration with protobuf 3.20.3. Tests compare all deployed descriptor fields,
round-trip old wire messages byte for byte, and preserve unknown fields. SDK
schema tests additionally decode historical claims; wallet tests cover claim
signatures. Updating a compiler or runtime must preserve these checks.
