"""Strict publishing tool inputs, separate from browser confirmation bodies."""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, field_validator, model_validator

from app.schemas.agent_content import BrandInput, Empty, Identity, Page, PostInput
from app.schemas.publish import MAX_PLATFORMS, Platform, PlatformOptions
from app.schemas.publish import PostInput as WebPostInput


class Posts(BrandInput, Page):
    status: (
        Literal[
            "draft",
            "scheduled",
            "paused",
            "publishing",
            "done",
            "partial",
            "failed",
            "missed",
            "cancelled",
        ]
        | None
    ) = None


class SaveDraft(BrandInput):
    post_id: Identity | None = None
    version: Identity | None = None
    format: Literal["video", "image", "carousel", "text", "story"]
    caption: str = Field(default="", max_length=63206)
    platform_captions: dict[Platform, str] = Field(default_factory=dict)
    platforms: list[Platform] = Field(max_length=MAX_PLATFORMS)
    # 省略代表沿用草稿原值（新草稿為 false），避免更新文案時不小心把貼文變成公開。
    facebook_unpublished: StrictBool | None = None
    platform_options: PlatformOptions | None = None
    media_ids: list[Identity] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def valid_update(self):
        if self.format != "story" and "caption" not in self.model_fields_set:
            raise ValueError("貼文須提供文案欄位")
        if self.post_id is not None and self.version is None:
            raise ValueError("更新須提供版本")
        WebPostInput(
            captions=self.platform_captions,
            facebook_unpublished=bool(self.facebook_unpublished),
            **self.model_dump(
                exclude={
                    "post_id",
                    "version",
                    "platform_captions",
                    "facebook_unpublished",
                    "media_ids",
                }
            ),
        )
        return self


class IdeaDraft(Empty):
    report_id: Identity
    idea_index: StrictInt = Field(ge=0)
    caption: str = Field(max_length=63206)


class Upload(PostInput):
    filename: str = Field(min_length=1, max_length=255)
    # thumbnail：YouTube 自訂縮圖；cover：Instagram Reels 封面；fb_cover：Facebook 影片／Reels 封面
    # （都只限影片草稿，不算發佈素材）；
    # 預設為一般素材。
    role: Literal["media", "thumbnail", "cover", "fb_cover"] = "media"


class RemoveMedia(PostInput):
    media_id: Identity


class Prepare(PostInput):
    version: Identity
    scheduled_at: AwareDatetime | None = None
    retry: StrictBool = False

    @field_validator("scheduled_at", mode="before")
    @classmethod
    def iso_time(cls, value):
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("時間須為含時區的 ISO 8601")
        return value


class Retry(PostInput):
    version: Identity


class Confirm(PostInput):
    confirmation_code: str = Field(min_length=1, max_length=100)
