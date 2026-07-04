class StageExecutionError(Exception):
    """Base class for errors raised by a run_stage service function (extraction
    or LLM-structuring failure). run_stage catches this base class so any
    current or future stage's service function can signal a stage failure
    without run_stage needing to know about each stage's specific exception
    type."""
