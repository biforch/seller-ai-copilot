from typing import Optional, List

from pydantic import BaseModel



class CreateProjectRequest(BaseModel):

    name: str

    description: Optional[str] = None

    platform: str = "Amazon"

    market: str = "USA"



class ProjectResponse(BaseModel):

    id: str

    name: str

    description: Optional[str]

    platform: str

    market: str

    status: str

    product_count: int = 0

    created_at: str



class ProjectDetailResponse(ProjectResponse):

    products: List[dict] = []