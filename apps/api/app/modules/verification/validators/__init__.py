"""The verified validator set, registered explicitly.

Adding a validator: implement it in this package (or a new module), then add an
instance here. The registry and pipeline need no changes — selection is driven
by each validator's own declaration.
"""

from __future__ import annotations

from app.modules.verification.contracts import VerificationValidator
from app.modules.verification.validators.data_analysis import (
    DataRecomputeValidator,
    LabConsistencyValidator,
)
from app.modules.verification.validators.mathematics import MathematicsValidator
from app.modules.verification.validators.programming import (
    ProgrammingExecutionValidator,
    PythonSyntaxValidator,
)
from app.modules.verification.validators.requirements import (
    RequirementComplianceValidator,
)
from app.modules.verification.validators.research import CitationValidator
from app.modules.verification.validators.structural import StructuralValidator
from app.modules.verification.validators.writing import (
    EssayStructureValidator,
    LanguageMetricsValidator,
    PresentationStructureValidator,
)

REGISTERED: tuple[VerificationValidator, ...] = (
    StructuralValidator(),
    RequirementComplianceValidator(),
    MathematicsValidator(),
    PythonSyntaxValidator(),
    ProgrammingExecutionValidator(),
    CitationValidator(),
    EssayStructureValidator(),
    PresentationStructureValidator(),
    LanguageMetricsValidator(),
    DataRecomputeValidator(),
    LabConsistencyValidator(),
)


def default_registry() -> object:
    from app.modules.verification.registry import ValidatorRegistry

    return ValidatorRegistry(REGISTERED)
