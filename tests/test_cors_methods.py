# The browser calls the API from another origin, so a route whose method CORS does not allow
# fails in the browser even though every server-side test passes. Keep the two in step.
from fastapi.middleware.cors import CORSMiddleware

from main import app


def test_every_route_method_is_allowed_by_cors():
    cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    allowed = set(cors.kwargs["allow_methods"])
    used = {method for route in app.routes for method in (getattr(route, "methods", None) or ())} - {"HEAD"}
    assert used <= allowed, f"methods used by routes but not allowed by CORS: {sorted(used - allowed)}"
