"""Unity compile check for the unity-support skill.

Wraps the existing unity_compile heartbeat check so it can be registered
via the skills system without duplicating logic.
"""

name = "unity_compile_skill"


def run(project_path: str, **kwargs):
    """Run the Unity compile check via the existing daemon check."""
    try:
        from daemon.checks import unity_compile
        return unity_compile.run(project_path)
    except Exception as e:
        from daemon.checks.base import CheckResult
        return CheckResult(
            check_name=name,
            ok=True,
            summary=f"Unity compile check unavailable: {e}",
        )
