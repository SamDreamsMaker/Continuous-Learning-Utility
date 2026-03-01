"""Exceptions for the skills subsystem."""


class SkillLoadError(Exception):
    """Raised when a skill fails to load."""


class SkillIntegrityError(SkillLoadError):
    """Raised when a skill's integrity check fails (SHA-256 mismatch)."""


class SkillRequirementError(SkillLoadError):
    """Raised when a skill's requirements are not met."""
