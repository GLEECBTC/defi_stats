#!/usr/bin/env python3
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from lib.dex_version import DexVersionService
from models.dex import DexVersionResponse
from models.generic import ErrorMessage

router = APIRouter()
service = DexVersionService()


@router.post(
    "/dex_version",
    description="Latest recommended AtomicDEX GUI version metadata.",
    response_model=DexVersionResponse,
    responses={503: {"model": ErrorMessage}},
    status_code=200,
)
def dex_version():
    info = service.get_version_info()
    if info is None:
        err = {"error": "Unable to fetch release metadata"}
        return JSONResponse(status_code=503, content=err)
    return info

