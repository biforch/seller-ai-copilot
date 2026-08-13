import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    auth,
    generate,
    products,
    project,
    user,
)
from app.core.config import settings
from app.core.exceptions import (
    AppException,
    _error_response,
    app_exception_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.rate_limit import limiter
from app.core.response import success_response

logging.basicConfig(
    level=logging.INFO
)

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
    docs_url="/docs",
    redoc_url="/redoc",
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





@app.get("/health")
async def health_check():

    return success_response(
        data={
            "status": "healthy",
            "service": "SellerAI Copilot API",
        }
    )





@app.get("/")
async def root():
    return success_response(
        data={
            "name": settings.APP_NAME,
            "docs": "/docs",
            "version": "1.0.0",
        },
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