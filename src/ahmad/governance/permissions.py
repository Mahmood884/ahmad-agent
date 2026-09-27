from enum import Enum


class PermissionLevel(str, Enum):
    READ_ONLY = "read_only"
    SAFE = "safe"
    PRIVILEGED = "privileged"


DEFAULT_PERMISSION = PermissionLevel.READ_ONLY
