"""One place that builds the Google GenAI client, so generation and judging can use either route.

  EA_GENAI_BACKEND=api     (default) the AI Studio API key: free tier, daily quotas.
  EA_GENAI_BACKEND=vertex  Vertex AI with application-default credentials: billed to the GCP project (credits),
                           needs GOOGLE_CLOUD_PROJECT (and optionally EA_VERTEX_LOCATION, default "global").
The model names are the same on both routes; only the client differs.
"""

from __future__ import annotations

import os
from typing import Any

REQUEST_TIMEOUT_MS = 60_000  # a hung call must fail and retry, not stall a run


def uses_vertex() -> bool:
    return os.environ.get("EA_GENAI_BACKEND", "api").strip().lower() == "vertex"


def make_genai_client(api_key: str = "") -> Any:
    from google import genai
    from google.genai import types

    if uses_vertex():
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        if not project:
            raise ValueError("EA_GENAI_BACKEND=vertex needs GOOGLE_CLOUD_PROJECT")
        return genai.Client(
            vertexai=True,
            project=project,
            location=os.environ.get("EA_VERTEX_LOCATION", "global"),
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
        )
    return genai.Client(api_key=api_key)
