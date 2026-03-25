from app.mcp_server import build_mcp_server


def main() -> None:
    server = build_mcp_server(secure_http=False)
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
