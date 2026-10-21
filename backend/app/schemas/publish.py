from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

Platform = Literal["facebook", "instagram", "threads", "youtube", "tiktok"]


class FacebookOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_format: Literal["feed", "reels"] | None = None


class InstagramOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    share_to_feed: StrictBool | None = None


class ThreadsOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segments: list[str] | None = Field(default=None, max_length=256)
    segments_custom: StrictBool | None = None

    @field_validator("segments")
    @classmethod
    def bounded_segments(cls, value):
        if value is not None and sum(len(text) for text in value) > 63206:
            raise ValueError("Threads 分段總文案過長")
        return value


class YoutubeOptions(BaseModel):
    # 縮圖由伺服端維護（上傳縮圖時綁定、移除時清除），輸入不接受 thumbnail_media_id。
    model_config = ConfigDict(extra="forbid")
    # 長度由發佈規則檢查（草稿可先存），這裡只限制資料量。
    title: str | None = Field(default=None, max_length=1000)
    privacy: Literal["public", "unlisted", "private"] | None = None
    made_for_kids: StrictBool | None = None


class TiktokOptions(BaseModel):
    # 隱私、音樂與文案都在 TikTok App 內完成，沒有可設定的欄位；只接受空物件。
    model_config = ConfigDict(extra="forbid")


class PlatformOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facebook: FacebookOptions | None = None
    instagram: InstagramOptions | None = None
    threads: ThreadsOptions | None = None
    youtube: YoutubeOptions | None = None
    tiktok: TiktokOptions | None = None


class IdeaDraftInput(BaseModel):
    # 舊畫面可能仍帶 include_script；草稿不再參考腳本，欄位直接忽略。
    model_config = ConfigDict(extra="ignore")
    report_id: int = Field(gt=0)
    idea_index: int = Field(ge=0)


class PresenceInput(BaseModel):
    brand_id: int = Field(gt=0)


class PostInput(BaseModel):
    brand_id: int = Field(gt=0)
    format: Literal["video", "image", "carousel", "text", "story"] = "text"
    caption: str = Field(default="", max_length=63206)
    captions: dict[Platform, str] = Field(default_factory=dict)
    platforms: list[Platform] = Field(default_factory=list, max_length=5)
    # 只影響 Facebook：貼文建立在粉專但不出現在粉專動態；Instagram／Threads 照常公開。
    facebook_unpublished: StrictBool = False
    platform_options: PlatformOptions | None = None
    media_ids: list[int] = Field(default_factory=list, max_length=20)
    version: int = Field(default=1, ge=1)

    @field_validator("captions")
    @classmethod
    def bounded_captions(cls, value):
        if any(len(text) > 63206 for text in value.values()):
            raise ValueError("文案過長")
        return value

    @model_validator(mode="after")
    def unpublished_needs_facebook(self):
        if self.facebook_unpublished and "facebook" not in self.platforms:
            raise ValueError("FB 草稿僅適用於 Facebook，請先選擇 Facebook")
        if self.format == "story" and (
            self.caption
            or self.captions
            or self.facebook_unpublished
            or "threads" in self.platforms
            or "youtube" in self.platforms
            or "tiktok" in self.platforms
            or len(self.media_ids) > 10
            or self.platform_options is not None
        ):
            raise ValueError("限時動態只含素材與 Facebook／Instagram，不支援文字或貼文選項")
        return self


class PublishAction(BaseModel):
    confirmed: Literal[True]
    version: int = Field(ge=1)
    scheduled_at: datetime | None = None

    @field_validator("scheduled_at")
    @classmethod
    def aware(cls, value):
        if value and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("時間須含時區")
        return value


class ThumbnailAction(BaseModel):
    confirmed: Literal[True]


class SwitchInput(BaseModel):
    enabled: bool
    confirmed: Literal[True]
