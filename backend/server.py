"""Entry point used by the systemd unit: `python -m backend.server`."""
import uvicorn

from . import config


def main() -> None:
    settings = config.load()
    uvicorn.run(
        "backend.main:app",
        host=settings.get("host", "0.0.0.0"),
        port=int(settings.get("port", 8686)),
        log_level="warning",
        access_log=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
