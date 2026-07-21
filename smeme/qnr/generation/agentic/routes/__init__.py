"""Agentic generation routes package.

Assembles sub-routers from each phase module into a single router
with the /qnr/agentic prefix.

Import path unchanged: ``from smeme.qnr.generation.agentic.routes import router``
"""

from fastapi import APIRouter

from smeme.qnr.generation.agentic.routes import (
    phase1_5_conclusions,
    phase1_research,
    phase2_design,
    phase3_build,
    utility,
)

router = APIRouter(prefix="/qnr/agentic", tags=["qnr-agentic"])

router.include_router(phase1_research.router)
router.include_router(phase1_5_conclusions.router)
router.include_router(phase2_design.router)
router.include_router(phase3_build.router)
router.include_router(utility.router)
