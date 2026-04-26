from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    REDIS_URL: str
    
    model_config = ConfigDict(env_file = ".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
