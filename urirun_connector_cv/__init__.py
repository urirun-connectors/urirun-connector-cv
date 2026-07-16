"""cv:// connector — structured field extraction from CVs/resumes (PDF/DOCX/image)."""
from .core import CV, parse, batch, doctor, main, urirun_bindings
__all__ = ["CV", "parse", "batch", "doctor", "main", "urirun_bindings"]
