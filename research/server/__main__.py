"""Explicit local/LAN launcher; never changes firewall or persists IP settings."""
import argparse
import ipaddress
import socket


def main():
    parser = argparse.ArgumentParser(description="NavGhost local-first telemetry observer")
    parser.add_argument("--lan", action="store_true", help="explicitly listen on trusted LAN interfaces")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be in 1..65535")
    try:
        import uvicorn
        import fastapi  # noqa: F401
        import websockets  # noqa: F401
    except ImportError:
        parser.exit(1, "Install dependencies first: .venv\\Scripts\\python.exe -m pip install -r requirements-command-center.txt\n")
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    print(f"NavGhost Command Center: http://127.0.0.1:{args.port}", flush=True)
    print(f"Phone endpoint: ws://<LAPTOP_IPV4>:{args.port}/ws/telemetry", flush=True)
    print(f"Port: {args.port}. Telemetry is in memory only; navigation stays on the phone.", flush=True)
    if args.lan:
        try:
            candidates = sorted({entry[4][0] for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                                 if ipaddress.ip_address(entry[4][0]).is_private and not ipaddress.ip_address(entry[4][0]).is_loopback})
        except OSError:
            candidates = []
        print("LAN mode explicitly enabled. Use only your trusted Wi-Fi/hotspot; ws:// is unencrypted.", flush=True)
        print("IPv4 candidates (choose the active Wi-Fi adapter; verify with ipconfig): " + (", ".join(candidates) or "unavailable"), flush=True)
    else:
        print("Local-only mode. For a trusted phone + laptop LAN, add --lan.", flush=True)
    uvicorn.run("server.app:app", host=host, port=args.port, workers=1, access_log=False,
                ws_max_size=16384, ws_max_queue=4, ws_ping_interval=20, ws_ping_timeout=20)


if __name__ == "__main__":
    main()
