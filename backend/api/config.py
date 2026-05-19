import os

class Settings:
    API_KEY: str = os.getenv('API_KEY', '')           # vazio = sem autenticação
    CORS_ORIGINS: list[str] = os.getenv('CORS_ORIGINS', '*').split(',')
    MAX_CONCURRENT_DOWNLOADS: int = int(os.getenv('MAX_CONCURRENT_DOWNLOADS', '3'))
    HOST: str = os.getenv('HOST', '127.0.0.1')
    PORT: int = int(os.getenv('PORT', '8000'))
    RATE_LIMIT_ANALYZE: str = os.getenv('RATE_LIMIT_ANALYZE', '30/minute')
    RATE_LIMIT_DOWNLOAD: str = os.getenv('RATE_LIMIT_DOWNLOAD', '10/minute')


settings = Settings()
