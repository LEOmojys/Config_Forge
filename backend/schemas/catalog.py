"""Catalog (lookup) schemas: elements, items, fixed reference data."""
from pydantic import BaseModel, Field
from .common import ElementId, ItemType


class ElementConfig(BaseModel):
    element_id: ElementId
    name: str = Field(min_length=1, max_length=32)
    color_hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class ItemConfig(BaseModel):
    item_id: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    item_type: ItemType
    rarity: int = Field(ge=1, le=5)
    description: str = Field(default="", max_length=256)
