from openbb_polymarket import create_app

app = create_app()


def main() -> None:
    import os

    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "7779")),
        timeout_graceful_shutdown=int(os.getenv("TIMEOUT_GRACEFUL_SHUTDOWN", "5")),
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "*"),
    )


if __name__ == "__main__":
    main()
