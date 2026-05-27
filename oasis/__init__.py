__version__ = "0.8.2"

__all__ = [
    "Platform",
    "Channel",
    "ActionType",
    "DefaultPlatformType",
]


def __getattr__(name: str):
    if name == "Platform":
        from oasis.social_platform.platform import Platform

        return Platform
    if name == "Channel":
        from oasis.social_platform.channel import Channel

        return Channel
    if name in {"ActionType", "DefaultPlatformType"}:
        from oasis.social_platform.typing import ActionType, DefaultPlatformType

        return {"ActionType": ActionType, "DefaultPlatformType": DefaultPlatformType}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
