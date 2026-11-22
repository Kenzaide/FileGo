"""Start the FileGo server.

  python run.py            stable server (waitress)
  python run.py --stream   streaming server (Werkzeug, threaded); use for experiments and the demo
"""
import argparse

from app import create_app
from app.meta import lan_addresses

app = create_app()  # also used by the `flask` CLI (FLASK_APP=run.py)


def main():
    parser = argparse.ArgumentParser(description="FileGo server")
    parser.add_argument("--stream", action="store_true", help="stream request bodies live")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=app.config["PORT"])
    args = parser.parse_args()

    app.config["PORT"] = args.port
    app.config["SERVER_MODE"] = "stream" if args.stream else "waitress"

    print(f"FileGo server mode: {app.config['SERVER_MODE']}")
    print(f"  This computer:  http://localhost:{args.port}")
    for a in lan_addresses():
        print(f"  On the network: http://{a['address']}:{args.port}   ({a['interface']})")
    print("Press Ctrl+C to stop.")

    if args.stream:
        app.run(host=args.host, port=args.port, threaded=True, debug=False)
    else:
        from waitress import serve

        serve(app, host=args.host, port=args.port, threads=8)


if __name__ == "__main__":
    main()
