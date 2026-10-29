"""Cliente GraphQL que reutiliza la sesión autenticada."""
from __future__ import annotations
import httpx
from .auth import NextAuthSession
from .models import Course, Video, VideoFile


class GQLError(Exception):
    pass


class GraphQLClient:
    def __init__(self, api_url: str, session: NextAuthSession):
        self.api_url = api_url
        self._http = session.client   # comparte cookies de sesión

    # ------------------------------------------------------------------
    def _query(self, query: str, variables: dict | None = None) -> dict:
        r = self._http.post(
            self.api_url,
            json={"query": query, "variables": variables or {}},
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        if errors := data.get("errors"):
            raise GQLError(errors[0]["message"])
        return data["data"]

    # ------------------------------------------------------------------
    def list_courses(self) -> list[Course]:
        """Devuelve todos los cursos con sus vídeos (sin streams, solo metadatos)."""
        data = self._query("""
        {
          courses {
            id name slug resourcePath
            videos {
              id name slug duration level isPublic
              resourcePath imageUrl description
              files { id url name }
            }
          }
        }
        """)
        courses = []
        for c in data["courses"]:
            videos = [
                Video(
                    id=v["id"],
                    name=v["name"],
                    slug=v["slug"],
                    duration=v["duration"],
                    level=v.get("level"),
                    is_public=v["isPublic"],
                    resource_path=v["resourcePath"],
                    image_url=v.get("imageUrl"),
                    description=v.get("description"),
                    files=[VideoFile(**f) for f in (v.get("files") or [])],
                )
                for v in (c.get("videos") or [])
            ]
            courses.append(
                Course(
                    id=c["id"],
                    name=c["name"],
                    slug=c["slug"],
                    resource_path=c["resourcePath"],
                    videos=videos,
                )
            )
        return courses

    # ------------------------------------------------------------------
    def get_video_stream(self, video_id: str) -> Video | None:
        """
        Obtiene los campos de stream de un vídeo concreto.
        Requiere sesión autenticada: hlsResourcePath y streamId solo se
        devuelven si el usuario tiene acceso al vídeo.
        """
        data = self._query(
            """
            query VideoStream($id: ID!) {
              videoById(id: $id) {
                id name slug duration level isPublic
                resourcePath imageUrl description
                hlsResourcePath streamId
                files { id url name }
              }
            }
            """,
            {"id": video_id},
        )
        v = data.get("videoById")
        if not v:
            return None
        return Video(
            id=v["id"],
            name=v["name"],
            slug=v["slug"],
            duration=v["duration"],
            level=v.get("level"),
            is_public=v["isPublic"],
            resource_path=v["resourcePath"],
            image_url=v.get("imageUrl"),
            description=v.get("description"),
            hls_resource_path=v.get("hlsResourcePath"),
            stream_id=v.get("streamId"),
            files=[VideoFile(**f) for f in (v.get("files") or [])],
        )
