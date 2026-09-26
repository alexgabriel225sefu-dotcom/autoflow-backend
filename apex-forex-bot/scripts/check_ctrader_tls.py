"""Verify the real TLS handshake to cTrader. No credentials required.

WHY THIS IS A SCRIPT AND NOT A TEST

A handshake needs the network, and cTrader's Open API listens on TCP 5035 —
raw TLS carrying protobuf, not HTTPS. An agent sandbox that only allows HTTPS
through an inspecting proxy cannot reach it: the proxy will accept a CONNECT to
5035 and then reset the TLS layer, because it cannot inspect a protocol it does
not speak. That is what happens in this project's development container, which
is why this could not be verified there and why it exists as something to run
elsewhere.

WHAT IT PROVES, AND WHAT IT DOES NOT

It proves the transport: that the host resolves, the port accepts, the
certificate chain validates against the system trust store, and the hostname
matches. **No credential is used and no account is touched** — it connects,
inspects, and hangs up before sending an application-auth message.

It proves nothing about OAuth, about an account, or about whether automation
works. `docs/CTRADER_DEMO_SMOKE_TEST.md` is for that.

RUN IT

    cd apex-forex-bot && python3 scripts/check_ctrader_tls.py
    cd apex-forex-bot && python3 scripts/check_ctrader_tls.py --env live   # read-only

Exit 0 means the handshake this bot relies on works from that host. Exit 1 means
it does not, and the reason is printed. Exit 2 means the host could not be
reached at all, which is a network answer rather than a TLS one.
"""
import argparse
import socket
import ssl
import sys

# The same endpoints apex/brokers/ctrader.py uses. Duplicated deliberately
# rather than imported: this script must be runnable on a box where the bot's
# configuration is absent, and importing the connector would pull in config
# that refuses to load without an encryption key.
HOSTS = {"demo": "demo.ctraderapi.com", "live": "live.ctraderapi.com"}
PORT = 5035

FAILED = []


def step(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  —  {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", choices=sorted(HOSTS), default="demo",
                    help="which cTrader endpoint to probe (default: demo)")
    ap.add_argument("--timeout", type=float, default=15.0)
    args = ap.parse_args(argv)
    host = HOSTS[args.env]

    print(f"cTrader TLS check — {host}:{PORT} ({args.env})")
    print("No credential is sent. The connection is closed before any "
          "application message.\n")

    # 1. DNS. A resolution failure is a different problem from a refused port,
    #    and reporting them as one sends somebody to the wrong place.
    try:
        addrs = socket.getaddrinfo(host, PORT, proto=socket.IPPROTO_TCP)
        step("the host resolves", True, f"{len(addrs)} address(es)")
    except OSError as e:
        step("the host resolves", False, f"{type(e).__name__}: {e}")
        print("\nDNS failed. Nothing further can be tested.")
        return 2

    # 2. TCP. On a network that only permits HTTPS, this is where it stops.
    try:
        raw = socket.create_connection((host, PORT), timeout=args.timeout)
        step("TCP 5035 accepts a connection", True)
    except OSError as e:
        step("TCP 5035 accepts a connection", False, f"{type(e).__name__}: {e}")
        print("\nPort 5035 is not reachable from this host. This is a network "
              "result, not a TLS one — the bot cannot run from here either.")
        return 2

    # 3. The handshake, with verification on. Exactly the context the connector
    #    builds: the system trust store, CERT_REQUIRED, check_hostname.
    ctx = ssl.create_default_context()
    step("the context requires a certificate",
         ctx.verify_mode == ssl.CERT_REQUIRED, str(ctx.verify_mode))
    step("the context checks the hostname", ctx.check_hostname is True)

    try:
        with ctx.wrap_socket(raw, server_hostname=host) as tls:
            step("the TLS handshake completes with verification on", True)
            step("a modern protocol was negotiated",
                 tls.version() in ("TLSv1.2", "TLSv1.3"), tls.version() or "?")
            cipher = tls.cipher()
            step("a cipher suite was agreed", bool(cipher),
                 cipher[0] if cipher else "none")

            cert = tls.getpeercert()
            step("the peer presented a certificate the trust store accepts",
                 bool(cert))
            if cert:
                # Printed because an operator comparing this against the
                # broker's published certificate needs it. Subject and issuer
                # of a public server certificate are not secrets.
                subject = {k: v for rdn in cert.get("subject", ())
                           for k, v in rdn}
                issuer = {k: v for rdn in cert.get("issuer", ()) for k, v in rdn}
                print(f"        subject CN : {subject.get('commonName', '?')}")
                print(f"        issuer     : {issuer.get('organizationName', '?')}")
                print(f"        not after  : {cert.get('notAfter', '?')}")
                sans = [v for t, v in cert.get("subjectAltName", ()) if t == "DNS"]
                step("the hostname is covered by the certificate's SANs",
                     any(s == host or (s.startswith("*.")
                         and host.endswith(s[1:])) for s in sans),
                     f"SANs: {', '.join(sans[:4])}")
    except ssl.SSLCertVerificationError as e:
        step("the TLS handshake completes with verification on", False,
             f"certificate verification FAILED: {e.verify_message or e}")
        print("\nThis is the serious outcome. Either the trust store on this "
              "host is missing a root, or something is intercepting the "
              "connection. Do not work around it by disabling verification.")
        return 1
    except (ssl.SSLError, OSError) as e:
        step("the TLS handshake completes with verification on", False,
             f"{type(e).__name__}: {e}")
        print("\nThe tunnel opened and TLS did not. On a network with an "
              "inspecting proxy this is expected for a non-HTTP port: the "
              "proxy cannot speak this protocol and resets it.")
        return 1

    print()
    if FAILED:
        print(f"FAILED ({len(FAILED)}): {', '.join(FAILED)}")
        return 1
    print("The verified TLS transport this bot depends on works from this host.")
    print("Record the date and the issuer in docs/DEPLOYMENT_READINESS.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
