from enum import StrEnum
from math import ceil
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

from app.core.exceptions import AppException

T = TypeVar("T")


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class PaginationParams(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    sort_by: str
    sort_order: SortOrder = SortOrder.DESC


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    pagination: PaginationMeta


def build_pagination_meta(page: int, page_size: int, total: int) -> PaginationMeta:
    total_pages = ceil(total / page_size) if total > 0 else 0
    return PaginationMeta(
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_next=page < total_pages if total_pages > 0 else False,
        has_previous=page > 1 and total > 0,
    )


def paginate_dict(items: list[dict], page: int, page_size: int, total: int) -> dict:
    return {
        "items": items,
        "pagination": build_pagination_meta(page, page_size, total).model_dump(),
    }


PROJECT_SORT_FIELDS = frozenset(
    {"name", "created_at", "updated_at", "status", "platform", "market"}
)
PRODUCT_SORT_FIELDS = frozenset({"name", "created_at", "category", "platform", "market"})


def pagination_dependency(
    *,
    allowed_sort_fields: frozenset[str],
    default_sort_by: str,
):
    def _dependency(
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        sort_by: str = Query(default_sort_by),
        sort_order: SortOrder = Query(SortOrder.DESC),
    ) -> PaginationParams:
        if sort_by not in allowed_sort_fields:
            raise AppException(
                message=f"Invalid sort_by: {sort_by}",
                code=422,
            )
        return PaginationParams(
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    return _dependency


ProjectPagination = pagination_dependency(
    allowed_sort_fields=PROJECT_SORT_FIELDS,
    default_sort_by="updated_at",
)
ProductPagination = pagination_dependency(
    allowed_sort_fields=PRODUCT_SORT_FIELDS,
    default_sort_by="created_at",
)
