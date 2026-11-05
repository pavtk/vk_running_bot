from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    DB_HOST: str = 'localhost'
    DB_PORT: int = 5432
    DB_NAME: str = 'postgresql'
    DB_USER: str = 'postgresql'
    DB_PASSWORD: str

    TIMEZONE: str = 'Europe/Moscow'

    VK_TOKEN: str

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )
    
    @property
    def database_url(self) -> URL:
        

        return URL.create(
            drivername='postgresql+asyncpg',
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        )

settings = Settings()
