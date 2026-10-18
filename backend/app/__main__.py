import uvicorn

from app.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    settings.assert_safe_bind()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.reload)
