import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.response import success_response
from app.core.security import get_current_user
from app.database.session import get_db
from app.schemas.pagination import PaginationParams, ProductPagination, ProjectPagination
from app.schemas.project import CreateProjectRequest
from app.services.project import ProjectService

router = APIRouter()

logger = logging.getLogger(__name__)


@router.post("")
def create_project(
    body: CreateProjectRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        project = ProjectService.create(
            db=db,
            user_id=current_user["id"],
            name=body.name,
            description=body.description,
            platform=body.platform,
            market=body.market,
        )
        return success_response(
            data={
                "id": str(project.id),
                "name": project.name,
                "description": project.description,
                "platform": project.platform,
                "market": project.market,
                "status": project.status,
                "created_at": project.created_at.isoformat(),
            },
            message="Project created successfully",
            code=201,
        )
    except Exception as e:
        logger.exception("Create project failed")
        raise AppException(
            message="Create project failed",
            code=500,
            detail=str(e) if settings.DEBUG else None,
        )


@router.get("")
def list_projects(
    pagination: PaginationParams = Depends(ProjectPagination),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    projects = ProjectService.get_user_projects(
        db=db,
        user_id=current_user["id"],
        params=pagination,
    )
    return success_response(data=projects)


@router.get("/{project_id}")
def get_project(
    project_id: str,
    pagination: PaginationParams = Depends(ProductPagination),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = ProjectService.get_project_detail(
        db=db,
        project_id=project_id,
        user_id=current_user["id"],
        params=pagination,
    )
    if not project:
        raise AppException(
            message="Project not found",
            code=status.HTTP_404_NOT_FOUND,
        )
    return success_response(data=project)


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deleted = ProjectService.delete(
        db=db,
        project_id=project_id,
        user_id=current_user["id"],
    )
    if not deleted:
        raise AppException(
            message="Project not found",
            code=status.HTTP_404_NOT_FOUND,
        )
    return success_response(
        data={"deleted": True},
        message="Project deleted successfully",
    )
