"""Vendored cTrader Open API protobuf message definitions.

WHY THESE FILES ARE IN THE REPOSITORY

The connector (`apex/brokers/ctrader.py`) speaks cTrader's protobuf protocol
over its own TLS socket. It needs the generated message classes and nothing
else — not the SDK's Twisted client, not its auth helpers. That was already
true, but the message classes came from the `ctrader-open-api` package, and
depending on that package for them cost more than it gave:

  * `ctrader_open_api/__init__.py` eagerly does `from .client import Client`,
    so importing any submodule — even a generated `_pb2` one — dragged in
    Twisted and pyOpenSSL. Neither is on any path this repository executes.
  * `ctrader-open-api==0.9.2` hard-pins `protobuf==3.20.1`, `pyOpenSSL==24.1.0`
    and `Twisted==24.3.0` with `==`, not `>=`. Those pins are the package's,
    not ours. They held `protobuf` at a version with open advisories, and no
    upgrade path existed: 0.9.2 is the newest release, and 0.9.3 was published
    and then yanked.
  * The SDK's `Client` connects with `clientFromString(reactor, "ssl:...")`,
    which builds an OpenSSL context with VERIFY_NONE — measured, on the
    installed version. Having it in the tree at all is a class of accident
    worth removing, since switching to it looks like a simplification.

Vendoring the four generated modules removes the package, and with it the three
transitive `==` pins, while changing nothing about what the connector sends or
parses. `protobuf` is now a direct dependency of ours, pinned in
requirements.txt, and can be bumped on its own schedule.

SOURCE

    package  ctrader-open-api
    version  0.9.2  (PyPI; https://github.com/spotware/openApiPy)
    license  MIT, Copyright (c) 2021 Spotware — see LICENSE in this directory
    files    ctrader_open_api/messages/OpenApiCommonMessages_pb2.py
             ctrader_open_api/messages/OpenApiCommonModelMessages_pb2.py
             ctrader_open_api/messages/OpenApiMessages_pb2.py
             ctrader_open_api/messages/OpenApiModelMessages_pb2.py

`OpenApiCommonMessages_pb2` imports `OpenApiCommonModelMessages_pb2`, and
`OpenApiMessages_pb2` imports `OpenApiModelMessages_pb2`, which is why four
files are here when the connector names three.

WHAT WAS CHANGED, AND NOTHING ELSE

One line in each of two files. The generated code reached its siblings with

    from ctrader_open_api.messages import X_pb2 as X__pb2

which cannot work once the files move, so it is now

    from . import X_pb2 as X__pb2

A relative import, so a future relocation needs no further edit. The serialized
descriptors, the message and enum definitions, the `_builder` calls and the
module-name strings passed to them are untouched — byte-identical to upstream.
Do not hand-edit anything else in these files; they are compiler output.

HOW TO REFRESH

    python3 -m pip download ctrader-open-api==<version> --no-deps -d /tmp/ctsdk
    cd /tmp/ctsdk && unzip -o ctrader_open_api-<version>-*.whl
    cp ctrader_open_api/messages/OpenApi*_pb2.py \\
       <repo>/apex-forex-bot/apex/ctrader_proto/
    cp ctrader_open_api-<version>.dist-info/LICENSE \\
       <repo>/apex-forex-bot/apex/ctrader_proto/LICENSE
    cd <repo>/apex-forex-bot/apex/ctrader_proto
    sed -i 's|^from ctrader_open_api\\.messages import |from . import |' *_pb2.py
    grep -rn ctrader_open_api . && echo "REFRESH INCOMPLETE"   # must print nothing

Then update the version above, run `python3 tests/run_all.py`, and confirm
`tests/test_broker_tls_posture.py` still reports no `ctrader_open_api` import
anywhere under `apex/` or `scripts/`. If upstream regenerates against a newer
protoc, the `protobuf` pin in requirements.txt may need to move with it.
"""
