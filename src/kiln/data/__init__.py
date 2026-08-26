"""Training-data tooling: format detection, linting, and inspection stats.

All torch-free by design — data commands must run on the light install.
"""

from kiln.data.formats import DataFormat, detect_format
from kiln.data.lint import LintIssue, lint_file

__all__ = ["DataFormat", "LintIssue", "detect_format", "lint_file"]
