import logging

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    amazon_accounts,
    amazon_listings,
    amazon_marketplaces,
    amazon_oauth,
    auth,
    generate,
    listing,
    products,
    project,
    user,
)
from app.core.access_log_safety import install_uvicorn_oauth_callback_access_log_filter
from app.core.auth_session_constants import SESSION_COOKIE_NAME
from app.core.config import settings
from app.core.csrf import CookieCsrfMiddleware
from app.core.exceptions import (
    AppException,
    _error_response,
    amazon_exception_handler,
    app_exception_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.log_filter import install_sensitive_data_log_filter
from app.core.rate_limit import limiter
from app.core.response import success_response
from app.database.session import get_db
from app.integrations.amazon.exceptions import AmazonError

logging.basicConfig(level=logging.INFO)

install_uvicorn_oauth_callback_access_log_filter()
install_sensitive_data_log_filter()

logger = logging.getLogger(__name__)


# Schema 现在完全由 Alembic 管理：
#   docker exec -it sellerai-backend bash
#   alembic upgrade head
# 部署/启动一个新环境时，先跑 alembic upgrade head，
# 不要指望这里自动建表了。


app = FastAPI(
    title="SellerAI Copilot API",
    description="AI-powered eCommerce Assistant for Global Sellers",
    version="1.0.0",
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)


app.state.limiter = limiter


async def rate_limit_handler(
    request: Request,
    exc: RateLimitExceeded,
):
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content=_error_response(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too Many Requests",
            str(exc.detail),
        ),
    )


app.add_exception_handler(
    RateLimitExceeded,
    rate_limit_handler,  # type: ignore[arg-type]  # Starlette handler variance
)


app.add_exception_handler(
    AppException,
    app_exception_handler,  # type: ignore[arg-type]
)


app.add_exception_handler(
    AmazonError,
    amazon_exception_handler,  # type: ignore[arg-type]
)


app.add_exception_handler(
    StarletteHTTPException,
    http_exception_handler,  # type: ignore[arg-type]
)


app.add_exception_handler(
    RequestValidationError,
    validation_exception_handler,  # type: ignore[arg-type]
)


# 兜底：任何没有被上面几个 handler 覆盖的异常
# （比如原始的 SQLAlchemy 错误）都会走这里，
# 保证前端拿到的是一个正常的 JSON 500，而不是一个
# 看起来像 CORS 报错、实际上啥信息都没有的失败请求。
app.add_exception_handler(
    Exception,
    unhandled_exception_handler,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(CookieCsrfMiddleware)


def custom_openapi():
    from fastapi.openapi.utils import get_openapi

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    components = openapi_schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    legacy_bearer_scheme = "HTTP" + "Bearer"
    security_schemes.pop(legacy_bearer_scheme, None)
    security_schemes["cookieAuth"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": SESSION_COOKIE_NAME,
    }

    public_paths = {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/amazon/oauth/callback",
        "/health",
        "/health/ready",
        "/",
    }
    for path, methods in openapi_schema.get("paths", {}).items():
        for method, operation in methods.items():
            if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            if path in public_paths:
                operation.pop("security", None)
                continue
            if path.startswith("/api/v1/"):
                operation["security"] = [{"cookieAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]


# =========================
# API Routes
# =========================


app.include_router(
    auth.router,
    prefix="/api/v1/auth",
    tags=["Authentication"],
)


app.include_router(
    products.router,
    prefix="/api/v1/products",
    tags=["Products"],
)


app.include_router(
    listing.router,
    prefix="/api/v1/products",
    tags=["Listing"],
)


if settings.LEGACY_GENERATION_ENABLED:
    app.include_router(
        generate.router,
        prefix="/api/v1/generate",
        tags=["Generate"],
    )


app.include_router(
    user.router,
    prefix="/api/v1/user",
    tags=["User"],
)


app.include_router(
    project.router,
    prefix="/api/v1/projects",
    tags=["Projects"],
)


app.include_router(
    amazon_oauth.router,
    prefix="/api/v1/amazon",
    tags=["Amazon OAuth"],
)


app.include_router(
    amazon_accounts.router,
    prefix="/api/v1/amazon",
    tags=["Amazon Accounts"],
)

app.include_router(
    amazon_marketplaces.router,
    prefix="/api/v1/amazon",
    tags=["Amazon Marketplaces"],
)

app.include_router(
    amazon_listings.router,
    prefix="/api/v1/amazon",
    tags=["Amazon Listings"],
)


@app.get("/health")
async def health_check():
    return success_response(
        data={
            "status": "healthy",
            "service": "SellerAI Copilot API",
        }
    )


@app.get("/health/ready")
def readiness_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    db.rollback()
    return success_response(
        data={
            "status": "ready",
            "service": "SellerAI Copilot API",
        }
    )


@app.get("/")
async def root():
    data = {
        "name": settings.APP_NAME,
        "version": "1.0.0",
    }
    if settings.api_docs_enabled:
        data["docs"] = "/docs"
    return success_response(
        data=data,
        message="Welcome to SellerAI Copilot API",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
