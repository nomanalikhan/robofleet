"""Gateway settings, read once from env."""

import os

from pydantic import BaseModel


class Config(BaseModel):
    site_id: str
    db_path: str = "/data/gateway.db"
    mqtt_host: str
    mqtt_port: int = 1883
    cleanix_discovery: str  # host:port that resolves to every Cleanix robot
    discovery_interval_s: float = 30
    poll_interval_s: float = 1
    uploaded_keep_s: float = 600  # keep uploaded history this long, a safety window
    retention_hours: float = 24  # hard cap for history that never got uploaded

    @classmethod
    def from_env(cls) -> "Config":
        fields = {name: os.environ[name.upper()] for name in cls.model_fields if name.upper() in os.environ}
        return cls(**fields)
