"""
Autenticación NextAuth con credenciales (email + password).
Flujo:
  1. GET /api/auth/csrf          → csrfToken
  2. POST /api/auth/callback/credentials → session cookie
"""
from __future__ import annotations
import httpx
from rich.console import Console

console = Console()


class AuthError(Exception):
    pass


class NextAuthSession:
    """
    Encapsula un cliente httpx autenticado con las cookies de NextAuth.
    Reutilizable en todas las llamadas posteriores (GraphQL, descargas).
    """

    def __init__(self, base_url: str, verify_ssl: bool = False):
        self.base_url = base_url.rstrip("/")
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
                "Accept": "application/json",
            },
        )
        self._logged_in = False

    # ------------------------------------------------------------------
    def login(self, email: str, password: str) -> None:
        # 1. CSRF token
        console.print("[dim]Obteniendo CSRF token…[/dim]")
        r = self.client.get(f"{self.base_url}/api/auth/csrf")
        r.raise_for_status()
        csrf = r.json().get("csrfToken", "")
        if not csrf:
            raise AuthError("No se pudo obtener el CSRF token")

        # 2. Credenciales
        console.print(f"[dim]Autenticando {email}…[/dim]")
        payload = {
            "csrfToken": csrf,
            "email": email,
            "password": password,
            "callbackUrl": self.base_url,
            "json": "true",
        }
        r2 = self.client.post(
            f"{self.base_url}/api/auth/callback/credentials",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        # NextAuth devuelve 200 o 401 según el resultado
        if r2.status_code == 401 or "CredentialsSignin" in r2.text:
            raise AuthError(f"Login fallido para {email}. Revisa las credenciales.")

        # Comprobar que tenemos cookie de sesión
        session_cookie = (
            self.client.cookies.get("__Secure-next-auth.session-token")
            or self.client.cookies.get("next-auth.session-token")
        )
        if not session_cookie:
            raise AuthError(
                "Login completado pero no se recibió cookie de sesión. "
                "¿El usuario tiene suscripción activa?"
            )

        self._logged_in = True
        console.print(f"[green]✓ Sesión iniciada como {email}[/green]")

    # ------------------------------------------------------------------
    def is_logged_in(self) -> bool:
        return self._logged_in

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
