import uuid

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.models.generation import Generation
from app.models.product import Product
from app.models.project import Project
from app.schemas.pagination import PaginationParams, SortOrder, paginate_dict


def _product_count_subquery(db: Session):
    return (
        db.query(
            Product.project_id.label("project_id"),
            func.count(Product.id).label("product_count"),
        )
        .group_by(Product.project_id)
        .subquery()
    )


def _generation_count_subquery(db: Session):
    return (
        db.query(
            Product.project_id.label("project_id"),
            func.count(Generation.id).label("generation_count"),
        )
        .join(Generation, Generation.product_id == Product.id)
        .group_by(Product.project_id)
        .subquery()
    )


def _per_product_generation_count_subquery(db: Session):
    return (
        db.query(
            Generation.product_id.label("product_id"),
            func.count(Generation.id).label("generations_count"),
        )
        .group_by(Generation.product_id)
        .subquery()
    )


def _apply_project_sort(query: Query, params: PaginationParams) -> Query:
    column = getattr(Project, params.sort_by)
    primary = column.asc() if params.sort_order == SortOrder.ASC else column.desc()
    id_order = Project.id.asc() if params.sort_order == SortOrder.ASC else Project.id.desc()
    if params.sort_by == "updated_at":
        return query.order_by(primary, Project.created_at.desc(), id_order)
    if params.sort_by == "created_at":
        return query.order_by(primary, id_order)
    return query.order_by(primary, Project.updated_at.desc(), Project.created_at.desc(), id_order)


def _apply_product_sort(query: Query, params: PaginationParams) -> Query:
    column = getattr(Product, params.sort_by)
    primary = column.asc() if params.sort_order == SortOrder.ASC else column.desc()
    id_order = Product.id.asc() if params.sort_order == SortOrder.ASC else Product.id.desc()
    return query.order_by(primary, id_order)


class ProjectService:
    @staticmethod
    def create(
        db: Session,
        user_id,
        name,
        description=None,
        platform="Amazon",
        market="USA",
    ):
        project = Project(
            user_id=user_id,
            name=name,
            description=description,
            platform=platform,
            market=market,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project

    @staticmethod
    def get_user_projects(
        db: Session,
        user_id,
        params: PaginationParams,
    ) -> dict:
        product_counts = _product_count_subquery(db)
        generation_counts = _generation_count_subquery(db)

        base = (
            db.query(
                Project,
                func.coalesce(product_counts.c.product_count, 0).label("product_count"),
                func.coalesce(generation_counts.c.generation_count, 0).label("generation_count"),
            )
            .outerjoin(product_counts, Project.id == product_counts.c.project_id)
            .outerjoin(generation_counts, Project.id == generation_counts.c.project_id)
            .filter(Project.user_id == user_id)
        )

        total = base.order_by(None).count()
        rows = (
            _apply_project_sort(base, params)
            .offset((params.page - 1) * params.page_size)
            .limit(params.page_size)
            .all()
        )

        items = [
            {
                "id": str(project.id),
                "name": project.name,
                "description": project.description,
                "platform": project.platform,
                "market": project.market,
                "status": project.status,
                "product_count": int(product_count),
                "generation_count": int(generation_count),
                "created_at": project.created_at.isoformat(),
                "updated_at": project.updated_at.isoformat(),
            }
            for project, product_count, generation_count in rows
        ]
        return paginate_dict(items, params.page, params.page_size, total)

    @staticmethod
    def get_project_detail(
        db: Session,
        project_id: str,
        user_id,
        params: PaginationParams,
    ) -> dict | None:
        try:
            project_uuid = uuid.UUID(project_id)
        except ValueError:
            return None

        project = (
            db.query(Project)
            .filter(
                Project.id == project_uuid,
                Project.user_id == user_id,
            )
            .first()
        )
        if not project:
            return None

        generation_counts = _per_product_generation_count_subquery(db)
        products_base = (
            db.query(
                Product,
                func.coalesce(generation_counts.c.generations_count, 0).label("generations_count"),
            )
            .outerjoin(generation_counts, Product.id == generation_counts.c.product_id)
            .filter(Product.project_id == project.id)
        )

        product_total = products_base.order_by(None).count()
        product_rows = (
            _apply_product_sort(products_base, params)
            .offset((params.page - 1) * params.page_size)
            .limit(params.page_size)
            .all()
        )

        product_items = [
            {
                "id": str(product.id),
                "name": product.name,
                "category": product.category,
                "platform": product.platform,
                "market": product.market,
                "generations_count": int(generations_count),
                "created_at": product.created_at.isoformat(),
            }
            for product, generations_count in product_rows
        ]

        return {
            "id": str(project.id),
            "name": project.name,
            "description": project.description,
            "platform": project.platform,
            "market": project.market,
            "status": project.status,
            "product_count": product_total,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat(),
            "products": paginate_dict(product_items, params.page, params.page_size, product_total),
        }

    @staticmethod
    def delete(
        db: Session,
        project_id: str,
        user_id,
    ) -> bool:
        try:
            project_uuid = uuid.UUID(project_id)
        except ValueError:
            return False

        project = (
            db.query(Project)
            .filter(
                Project.id == project_uuid,
                Project.user_id == user_id,
            )
            .first()
        )
        if not project:
            return False

        db.delete(project)
        db.commit()
        return True
