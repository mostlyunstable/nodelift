from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.domain.ports import CodeRunner, CodeRunResult, JsonValue

router = APIRouter(prefix="/nodes", tags=["nodes"])


class CodeTestRequest(BaseModel):
    source: str = Field(max_length=200_000)
    input: JsonValue = None
    timeout_ms: int = Field(default=5000, ge=100, le=30_000)


def get_runner(request: Request) -> CodeRunner:
    runner: CodeRunner = request.app.state.runner
    return runner


@router.post("/code/test", response_model=CodeRunResult)
async def test_code(
    req: CodeTestRequest, runner: Annotated[CodeRunner, Depends(get_runner)]
) -> CodeRunResult:
    return await runner.run(req.source, req.input, req.timeout_ms / 1000)
