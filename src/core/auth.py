"""
Autenticación vía GraphQL mutation:
  login(input: {username, password}) → { accessToken }

El token JWT se usa como Bearer en todas las peticiones posteriores.
"""
from __future__ import annotations
import httpx
from rich.console import Console

console = Console()

API_URL = "https://api.escueladebajistas.com/graphql"


class AuthError(Exception):
    pass


class JWTSession:
    """
    Sesión autenticada con Bearer token JWT.
    Reutilizable para todas las llamadas GraphQL y descargas.
    """

    def __init__(self, verify_ssl: bool = False):
        self.token: str = ""
        self.client = httpx.Client(
            verify=verify_ssl,
            follow_redirects=True,
            timeout=30,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )

    # ------------------------------------------------------------------
    def login(self, username: str, password: str) -> None:
        console.print(f"[dim]Autenticando {username}…[/dim]")

        r = self.client.post(
            API_URL,
            json={
                "query": """
                    mutation Login($u: String!, $p: String!) {
                      login(input: { username: $u, password: $p }) {
                        accessToken
                      }
                    }
                """,
                "variables": {"u": username, "p": password},
            },
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()

        if errors := data.get("errors"):
            raise AuthError(f"Login fallido: {errors[0]['message']}")

        self.token = data["data"]["login"]["accessToken"]
        if not self.token:
            raise AuthError("Login OK pero no se recibió accessToken")

        # Inyectar Bearer en todas las peticiones futuras
        self.client.headers["Authorization"] = f"Bearer {self.token}"
        console.print(f"[green]✓ Sesión JWT iniciada como {username}[/green]")

    # ------------------------------------------------------------------
    def is_logged_in(self) -> bool:
        return bool(self.token)

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
