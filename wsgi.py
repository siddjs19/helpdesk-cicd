"""WSGI entry point used by gunicorn and by `flask run`.

gunicorn --bind 0.0.0.0:8000 wsgi:app
"""

from __future__ import annotations

import os

from app import create_app
from app.config import ProductionConfig

# ProductionConfig is only used when ENVIRONMENT=production, otherwise the
# development defaults apply (insecure key, non-secure cookies).
config = ProductionConfig if os.environ.get("ENVIRONMENT") == "production" else None
app = create_app(config)


if __name__ == "__main__":  # pragma: no cover
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=True)
