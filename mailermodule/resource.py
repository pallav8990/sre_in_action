from fastapi import APIRouter, Request
from pydantic import BaseModel
from utils.mailme_decorator import mailme

router = APIRouter(prefix="/api/v1/resource", tags=["resource"])

class ItemOut(BaseModel):
    id: str
    value: str

@router.get("/items/{item_id}", response_model=ItemOut)
@mailme()  # add ?mailme=true to trigger email
async def get_item(item_id: str, request: Request):
    return ItemOut(id=item_id, value="hello")