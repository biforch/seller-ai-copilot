from typing import List, Optional

from pydantic import BaseModel



class GenerateListingRequest(BaseModel):

    # Product 必须属于 Project
    project_id: str

    # 已存在商品时使用
    product_id: Optional[str] = None

    name: str

    category: str

    market: str = "USA"

    platform: str = "Amazon"

    # 目标客户，未提供时沿用已保存的 Product 上下文
    target_customer: Optional[str] = None

    # 产品卖点/优势，未提供时沿用已保存的 Product 上下文
    advantages: Optional[List[str]] = None




class GenerateListingResponse(BaseModel):

    project_id: str

    product_id: str

    title: str

    bullets: List[str]

    description: str

    keywords: List[str]

    tokens_used: int





class AnalyzeRequest(BaseModel):

    # 分析结果可以只属于 Project
    project_id: str

    title: str

    reviews: int

    rating: float

    description: str





class AnalyzeResponse(BaseModel):

    project_id: str

    strengths: List[str]

    weaknesses: List[str]

    opportunities: List[str]

    tokens_used: int





class GenerationHistoryItem(BaseModel):

    id: str

    type: str

    project_id: Optional[str] = None

    product_id: Optional[str] = None

    input: dict

    output: dict

    tokens_used: int

    created_at: str