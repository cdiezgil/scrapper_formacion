from __future__ import annotations
from pydantic import BaseModel
from typing import Optional


class VideoFile(BaseModel):
    id: str
    url: str
    name: str


class Video(BaseModel):
    id: str
    name: str
    slug: str
    duration: int                    # segundos
    level: Optional[str] = None
    is_public: bool
    resource_path: str
    image_url: Optional[str] = None
    description: Optional[str] = None
    hls_resource_path: Optional[str] = None
    stream_id: Optional[str] = None
    files: list[VideoFile] = []      # materiales descargables

    @property
    def duration_str(self) -> str:
        m, s = divmod(self.duration, 60)
        return f"{m}m{s:02d}s"

    @property
    def safe_name(self) -> str:
        import re
        return re.sub(r'[^\w\s-]', '', self.name).strip().replace(' ', '_')


class Course(BaseModel):
    id: str
    name: str
    slug: str
    resource_path: str
    videos: list[Video] = []

    @property
    def safe_name(self) -> str:
        import re
        return re.sub(r'[^\w\s-]', '', self.name).strip().replace(' ', '_')
