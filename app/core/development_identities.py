DEVELOPMENT_IDENTITY_MAP = {
    **{f"test-user-{index:02d}": "TEST_PLATFORM" for index in range(1, 9)},
    **{f"demo_user_{index:03d}": "WEB" for index in range(1, 9)},
}


def resolve_development_platform_type(platform_user_id: str) -> str | None:
    return DEVELOPMENT_IDENTITY_MAP.get(platform_user_id)


def is_allowed_development_identity(platform_type: str, platform_user_id: str) -> bool:
    expected_platform_type = resolve_development_platform_type(platform_user_id)
    return expected_platform_type is not None and platform_type == expected_platform_type
