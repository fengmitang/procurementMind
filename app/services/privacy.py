def mask_mobile(mobile: str | None) -> str | None:
    if mobile is None or len(mobile) < 7:
        return mobile
    return f"{mobile[:3]}****{mobile[-4:]}"


def mask_bank_account(account: str | None) -> str | None:
    if account is None or len(account) < 8:
        return account
    return f"{account[:4]}****{account[-4:]}"
