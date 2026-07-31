"""Local development server.

Usage:
    python run.py            # Waitress server on port 5000
    python run.py --debug    # Flask dev server with auto-reload (dev only)
"""

import sys

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402

app = create_app()


def main():
    debug = "--debug" in sys.argv
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 5000
    host = "0.0.0.0"
    if debug:
        # NOTE: never use --debug in production.
        app.run(debug=True, host=host, port=port)
    else:
        from waitress import serve

        print(f"Serving on http://{host}:{port}")
        serve(app, host=host, port=port)


if __name__ == "__main__":
    main()
