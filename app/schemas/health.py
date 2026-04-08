from pydantic import BaseModel


class DependencyHealth(BaseModel):
    ok: bool
    details: str


class HealthResponse(BaseModel):
    service: str
    environment: str
    instance: str
    postgres: DependencyHealth
    redis: DependencyHealth

