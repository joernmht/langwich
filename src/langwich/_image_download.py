"""Isolated HTTP image download; the caller enforces the overall deadline."""

from __future__ import annotations

import base64
import http.client
import json
import sys
import urllib.request


def main() -> None:
    request_data = json.load(sys.stdin)
    url = request_data["url"]
    limit = request_data["limit"]
    request = urllib.request.Request(url, headers={"User-Agent": request_data["agent"]})
    try:
        with urllib.request.urlopen(request, timeout=request_data["timeout"]) as response:
            declared = response.headers.get("Content-Length")
            length = int(declared) if declared is not None else None
            if length is not None and length < 0:
                raise ValueError("invalid Content-Length")
            if length is not None and length > limit:
                raise ValueError("image is too large")
            raw = response.read(limit + 1)
            if len(raw) > limit:
                raise ValueError("image is too large")
            if length is not None and len(raw) != length:
                raise ValueError(f"ended after {len(raw)} of {length} declared bytes")
        json.dump({"data": base64.b64encode(raw).decode("ascii")}, sys.stdout)
    except (http.client.HTTPException, OSError, ValueError) as exc:
        json.dump({"error": f"{type(exc).__name__}: {exc}"}, sys.stdout)


if __name__ == "__main__":
    main()
