from typing import List, Optional

from pydantic import BaseModel



class CreateProductRequest(BaseModel):

    project_id: str

    name: str

    category: Optional[str] = None

    platform: str = "Amazon"

    market: str = "USA"

    target_customer: Optional[str] = None

    advantages: Optional[List[str]] = None




class ProductResponse(BaseModel):

    id: str

    name: str

    category: Optional[str]

    platform: str

    market: str

    project_id: str

    target_customer: Optional[str] = None

    advantages: Optional[List[str]] = None

    created_at: str





class GenerationRecord(BaseModel):

    id: str

    type: str

    input: dict

    output: dict

    tokens_used: int

    created_at: str





class ProductDetailResponse(ProductResponse):

    project: dict

    stats: dict

    score: Optional[dict] = None

    next_actions: List[dict] = []

    generations: List[GenerationRecord] = []