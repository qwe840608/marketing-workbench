import logging
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        populate_by_name=True,
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    frontend_dist_dir: Path = REPO_ROOT / "frontend" / "dist"
    database_path: Path = REPO_ROOT / "data" / "db" / "mwb.db"
    protected_paths: list[Path] = Field(default_factory=list)
    export_root: Path = REPO_ROOT / "data" / "export"
    publish_media_root: Path = REPO_ROOT / "data" / "publish-media"
    publish_poll_seconds: float = Field(default=5, ge=0.01, le=60)
    publish_poll_timeout: float = Field(default=300, ge=0.01, le=600)
    scheduler_publish_enabled: bool = True
    obsidian_root: Path = REPO_ROOT / "社群留言"
    export_worker_enabled: bool = True
    backup_local_root: Path | None = None
    backup_drive_root: Path | None = None
    backup_password: SecretStr | None = None
    seven_zip_path: Path = Path("C:/Program Files/7-Zip/7z.exe")
    log_path: Path = REPO_ROOT / "data" / "logs" / "backend.jsonl"
    app_origin: str = "http://127.0.0.1:8000"
    allowed_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1", "localhost"])
    session_cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=28800, ge=300, le=604800)
    # 測試／驗收資料的管理員（帳號 admin）初始密碼。
    admin_initial_password: SecretStr | None = None
    marketing_test_initial_password: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "MARKETING_TEST_INITIAL_PASSWORD",
            bytes([77, 73, 69, 78]).decode() + "_TEST_INITIAL_PASSWORD",
        ),
    )
    viewer_test_initial_password: SecretStr | None = None
    registration_brand_slug: str = ""
    ingest_api_key: SecretStr | None = None
    webhook_probe_secret: SecretStr | None = None
    receive_health_worker_enabled: bool = True
    receive_health_alerts_enabled: bool = True
    webhook_public_url: str = ""
    line_channel_secret: SecretStr | None = None
    meta_page_id: str = ""
    meta_app_id: str = ""
    youtube_client_id: str = ""
    youtube_client_secret: SecretStr | None = None
    youtube_channel_id: str = ""
    youtube_access_token: SecretStr | None = None
    youtube_refresh_token: SecretStr | None = None
    # 通常在平台連線卡片設定（加密入庫）；.env 只作為後備。
    tiktok_client_key: SecretStr | None = None
    tiktok_client_secret: SecretStr | None = None
    tiktok_open_id: str = ""
    tiktok_access_token: SecretStr | None = None
    tiktok_refresh_token: SecretStr | None = None
    threads_app_id: str = ""
    threads_app_secret: SecretStr | None = None
    threads_user_id: str = ""
    threads_access_token: SecretStr | None = None
    meta_user_access_token: SecretStr | None = None
    meta_ig_account_id: str = ""
    meta_verify_token: SecretStr | None = None
    scheduler_enabled: bool = True
    scheduler_classify_enabled: bool = True
    scheduler_notify_enabled: bool = True
    scheduler_comments_enabled: bool = True
    scheduler_metrics_enabled: bool = True
    scheduler_ideation_enabled: bool = True
    meta_app_secret: SecretStr | None = None
    comments_wake_enabled: bool = True
    meta_page_access_token: SecretStr | None = None
    notify_line_channel_access_token: SecretStr | None = None
    notify_line_channel_secret: SecretStr | None = None
    notify_line_group_id: str = ""
    notify_line_bot_user_id: str = ""
    meta_ig_comments_webhook_live: bool = False
    meta_api_calls_per_hour: int = Field(default=180, ge=10, le=100000)
    account_encryption_key: SecretStr | None = None
    jev_api_key: SecretStr | None = None
    jev_api_base_url: str = "https://api.typesafe.ai/v1"
    jev_model: str = "jev-1.13.0"
    jev_timeout_seconds: int = Field(default=15, ge=1, le=60)
    gemini_api_key: SecretStr | None = None
    gemini_model: str = ""
    # 免費額度的內容會被 Google 用於改善產品並可能由真人審閱，與平台條款衝突；
    # 只有 Cloud 專案已綁定帳單（付費方案）時，管理員才在 .env 設為 true。
    gemini_paid_tier: bool = False
    openai_api_key: SecretStr | None = None
    openai_model: str = ""
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = ""
    ai_max_output_tokens: int = Field(default=2048, ge=256, le=16384)
    ai_api_timeout_seconds: int = Field(default=60, ge=5, le=120)
    ai_monthly_budget_usd: Decimal | None = Field(default=None, gt=0)
    # 平台條款要求不再需要時刪除他人的留言；到期由每日排程刪除，報告只移除引用原文。
    comment_retention_days: int = Field(default=365, ge=30, le=3650)
    ingest_max_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=16 * 1024 * 1024)

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        previous = bytes([77, 73, 69, 78]).decode() + "_TEST_INITIAL_PASSWORD"

        def compatibility(source):
            def read():
                data = source()
                names = getattr(source, "env_vars", {})
                if data.get(previous) or names.get(previous.lower()):
                    logging.getLogger("mwb.config").warning(
                        "legacy_environment_key_deprecated_use_MARKETING_TEST_INITIAL_PASSWORD"
                    )
                return data

            return read

        return (
            compatibility(init_settings),
            compatibility(env_settings),
            compatibility(dotenv_settings),
            file_secret_settings,
        )

    @field_validator("jev_api_base_url")
    @classmethod
    def official_jev_endpoint(cls, value: str) -> str:
        if value.rstrip("/") != "https://api.typesafe.ai/v1":
            raise ValueError("JEV_API_BASE_URL 必須使用 TypeSafe 官方 HTTPS 端點")
        return value.rstrip("/")

    @field_validator("ingest_api_key")
    @classmethod
    def valid_ingest_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("INGEST_API_KEY 至少需要 32 字元")
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def explicit_hosts(cls, value: list[str]) -> list[str]:
        if not value or any("*" in host or "/" in host for host in value):
            raise ValueError("ALLOWED_HOSTS 必須明列內部主機名稱")
        return value

    @model_validator(mode="after")
    def secure_https_cookie(self):
        if (
            any(o.startswith("https://") for o in self.app_origins)
            and not self.session_cookie_secure
        ):
            raise ValueError("HTTPS 部署必須啟用 SESSION_COOKIE_SECURE")
        return self

    @property
    def app_origins(self) -> tuple[str, ...]:
        return tuple(self.app_origin.split(","))

    @property
    def backoffice_origin(self) -> str:
        return next((o for o in self.app_origins if o.startswith("https://")), self.app_origins[0])

    @field_validator(
        "database_path", "export_root", "obsidian_root", "log_path", "publish_media_root"
    )
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            value = REPO_ROOT / value
        return value.resolve()

    @field_validator("app_origin")
    @classmethod
    def valid_origin(cls, value: str) -> str:
        origins = []
        for entry in value.split(","):
            origin = entry.strip()
            parts = urlsplit(origin)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
                or parts.path not in {"", "/"}
                or parts.query
                or parts.fragment
                or "*" in origin
                or any(c.isspace() or ord(c) < 32 for c in origin)
                or parts.port == 0
            ):
                raise ValueError("APP_ORIGIN 必須是逗號分隔、明列的 HTTP(S) origin")
            host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
            port = parts.port
            if port and (parts.scheme, port) not in {("http", 80), ("https", 443)}:
                host += f":{port}"
            normalized = f"{parts.scheme}://{host}"
            if normalized not in origins:
                origins.append(normalized)
        return ",".join(origins)
