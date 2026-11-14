"""Tech Drona LMS edge for Firebase: the Next.js BFF ported to ASGI, in front of the FastAPI app.

On the VM the browser talks to the Next.js BFF (apps/web/src/lib/bff/*, app/api/**/route.ts),
which holds the HttpOnly cookies, checks CSRF and Fetch Metadata and calls the API with the
service token. On Firebase, Hosting rewrites ``/api/**`` to the ``lmsApi`` function, which runs
``EdgeApp(api_app)``: the same checks and responses, then an in-process ASGI call into the
unchanged FastAPI app (no network hop).

Firebase Hosting forwards only the cookie named ``__session`` to functions, so the session,
device, remember-me and CSRF cookie values travel packed in ``__session`` (``cookies.py``). The
JavaScript-readable ``td_csrf`` cookie is still set exactly as before for the double submit.
"""

from lms_edge.app import EdgeApp
from lms_edge.config import EdgeConfig, load_config

__all__ = ["EdgeApp", "EdgeConfig", "load_config"]
