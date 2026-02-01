import re


_VERSION_RE = re.compile(r"\bv\d+(?:\.\d+){0,3}\b", re.IGNORECASE)
_BRACKET_TAG_RE = re.compile(r"\[[^\]]+\]")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")
_DRIVE_PATH_RE = re.compile(r"^[a-zA-Z]:[\\/]")
_FILE_EXT_RE = re.compile(r"\.(exe|py|rpy|rpyc|bat|cmd|dll)\b", re.IGNORECASE)


def sanitize_title(title: str) -> str:
    title = title or ""
    title = _BRACKET_TAG_RE.sub("", title)
    title = _VERSION_RE.sub("", title)
    title = title.replace("—", "-")
    title = _MULTI_SPACE_RE.sub(" ", title)
    return title.strip(" -\t\r\n")


def looks_like_path(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    if _DRIVE_PATH_RE.match(text):
        return True
    if text.startswith("\\\\"):
        return True
    if ("\\" in text) or ("/" in text):
        if ":" in text:
            return True
        if _FILE_EXT_RE.search(text):
            return True
    return False
