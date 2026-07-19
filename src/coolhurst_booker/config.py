from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    coolhurst_username: str = ""
    coolhurst_password: str = ""
    coolhurst_base_url: str = "https://coolhurst.clubsolution.co.uk/newlook"
    coolhurst_booking_area: str = "Outdoor Tennis"
    coolhurst_days_ahead: int = 14
    coolhurst_db_path: str = "./data/courts.db"
    playwright_headless: bool = True
    scrape_interval_seconds: int = 300
    health_warn_after_seconds: int = 300
    health_stale_after_seconds: int = 3600

    booker_name: str = "Roshan"
    google_appointment_url: str = ""
    coolhurst_book_url: str = (
        "https://coolhurst.clubsolution.co.uk/newlook/proc_baner.asp"
    )
    show_public_court_calendar_link: bool = True
    google_username: str = ""
    google_password: str = ""

    @property
    def proc_baner_url(self) -> str:
        return f"{self.coolhurst_base_url}/proc_baner.asp"

    @property
    def ajax_url(self) -> str:
        return f"{self.coolhurst_base_url}/ajax.asp"


def get_settings() -> Settings:
    return Settings()
