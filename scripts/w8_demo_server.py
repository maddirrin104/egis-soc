"""Serve the W8 synthetic report UI on loopback only."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from wsgiref.simple_server import make_server

from egis_soc.w8_api import create_app
from egis_soc.w8_auth import ReviewIdentity, ReviewSessions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--review-dir", type=Path,
                        help="Existing owner-protected directory outside this repository")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    identity = ReviewIdentity.from_environment()
    sessions = ReviewSessions(identity) if identity is not None else None
    environment_dir = os.environ.get("EGIS_REVIEW_DIR")
    review_dir = args.review_dir or (Path(environment_dir) if environment_dir else None)
    if sessions is None and review_dir is not None:
        raise ValueError("review_credentials_required_for_directory")
    if sessions is not None:
        if review_dir is None or os.name != "nt":
            raise ValueError("windows_owner_review_directory_required")
        checked = subprocess.run(
            ["powershell", "-NoProfile", "-File",
             str(root / "scripts" / "w8_review_dir.ps1"),
             "-Check", "-Path", str(review_dir)],
            capture_output=True, text=True, check=False,
        )
        if checked.returncode != 0:
            raise ValueError("review_directory_acl_check_failed") from None
    app = create_app(root, sessions=sessions, review_directory=review_dir)
    with make_server("127.0.0.1", args.port, app) as server:
        print(f"W8 synthetic offline demo: http://127.0.0.1:{server.server_port}/", flush=True)
        print("Analyst review: " + ("AUTHENTICATED_LOCAL" if sessions else "DISABLED"),
              flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
