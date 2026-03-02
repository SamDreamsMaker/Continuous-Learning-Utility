"""Custom exception hierarchy for CLU."""


class AgentError(Exception):
    """Base exception for all agent errors."""
    pass


class SandboxViolation(AgentError):
    """Raised when a file operation violates sandbox rules."""
    pass


class LMStudioError(AgentError):
    """Raised when LM Studio is unreachable or returns an error."""
    pass


class ToolExecutionError(AgentError):
    """Raised when a tool fails to execute."""
    pass


class ValidationError(AgentError):
    """Raised when C# validation fails."""
    pass


class BudgetExhaustedError(AgentError):
    """Raised when iteration or token budget is exhausted."""
    pass


class ContextOverflowError(AgentError):
    """Raised when the prompt exceeds the model's context window."""
    pass
