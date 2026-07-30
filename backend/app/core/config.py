from pydantic import field_validator
from pydantic_settings import BaseSettings



class Settings(BaseSettings):


    # Database

    DATABASE_URL: str = (
        "postgresql://sellerai:sellerai123@postgres:5432/sellerai"
    )


    REDIS_URL: str = (
        "redis://redis:6379"
    )



    # ==================
    # AI
    # ==================

    OPENAI_API_KEY: str


    OPENAI_BASE_URL: str = (
        "https://openrouter.ai/api/v1"
    )


    OPENAI_MODEL: str = (
        "openai/gpt-4o-mini"
    )


    OPENAI_FALLBACK_MODELS: str = ""


    OPENAI_REFERER: str = (
        "http://localhost:3000"
    )


    OPENAI_TITLE: str = (
        "SellerAI Copilot"
    )


    OPENAI_TIMEOUT: float = 120.0



    # ==================
    # JWT
    # ==================

    JWT_SECRET_KEY: str = (
        "your-super-secret-jwt-key-change-me"
    )


    JWT_ALGORITHM: str = "HS256"


    JWT_EXPIRE_MINUTES: int = 1440



    # ==================
    # CORS
    # ==================

    CORS_ORIGINS: str = (
        "http://localhost:3000"
    )



    # APP

    APP_NAME: str = (
        "SellerAI Copilot"
    )


    DEBUG: bool = True



    @field_validator(
        "CORS_ORIGINS",
        mode="before"
    )
    @classmethod
    def parse_cors_origins(
        cls,
        v
    ):

        if isinstance(v,list):
            return ",".join(v)

        return v



    @property
    def cors_origins_list(self):

        if self.CORS_ORIGINS=="*":
            return ["*"]

        return [
            x.strip()
            for x in self.CORS_ORIGINS.split(",")
            if x.strip()
        ]



    class Config:

        env_file=".env"

        case_sensitive=True



settings = Settings()