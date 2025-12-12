from pydantic import BaseModel


class DexVersionResponse(BaseModel):
    status: str
    new_version: str
    changelog: str
    download_url: str

