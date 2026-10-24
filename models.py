"""Provided: input schemas live beside the tool interface."""
from typing import Literal
from pydantic import BaseModel, Field

class NoInput(BaseModel):
    pass

class SearchInput(BaseModel):
    query: str = Field(min_length=1, description="Product name the customer requested.")

class OrderItem(BaseModel):
    product_id: Literal["cold_coffee", "paneer_tikka", "veg_sandwich", "lemonade"]
    quantity: int = Field(ge=1, le=20, strict=True)

class OrderInput(BaseModel):
    items: list[OrderItem] = Field(min_length=1, max_length=4)
