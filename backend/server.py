"""Entry point — mirrors the existing backend's src/main.py pattern."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.api.app import create_app  # noqa: E402

app = create_app()


def main() -> None:
    import uvicorn
    from src.infrastructure.config import get_settings
    s = get_settings()
    uvicorn.run(app, host=s.host, port=s.port, log_config=None)


if __name__ == "__main__":
    main()
