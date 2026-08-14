import uuid

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.core.orm_utils import orm_dict, orm_uuid
from app.models.generation import Generation
from app.models.product import Product
from app.models.project import Project
from app.schemas.pagination import PaginationParams, SortOrder, paginate_dict
from app.services.scoring import build_next_actions, compute_listing_score


def _generation_count_subquery(db: Session):
    return (
        db.query(
            Generation.product_id.label("product_id"),
            func.count(Generation.id).label("generations_count"),
        )
        .group_by(Generation.product_id)
        .subquery()
    )


def _apply_product_sort(query: Query, params: PaginationParams) -> Query:
    column = getattr(Product, params.sort_by)
    primary = column.asc() if params.sort_order == SortOrder.ASC else column.desc()
    id_order = Product.id.asc() if params.sort_order == SortOrder.ASC else Product.id.desc()
    return query.order_by(primary, id_order)


class ProductService:
    """商品业务逻辑."""

    @staticmethod
    def create(
        db: Session,
        user_id: str,
        project_id: str,
        name: str,
        category: str | None = None,
        platform: str = "Amazon",
        market: str = "USA",
        target_customer: str | None = None,
        advantages: list[str] | None = None,
        *,
        commit: bool = True,
    ) -> Product:
        project = (
            db.query(Project)
            .filter(
                Project.id == project_id,
                Project.user_id == uuid.UUID(str(user_id)),
            )
            .first()
        )
        if not project:
            raise ValueError("Project not found")

        product = Product(
            user_id=user_id,
            project_id=project_id,
            name=name,
            category=category,
            platform=platform,
            market=market,
            target_customer=target_customer,
            advantages=advantages,
        )
        db.add(product)
        if commit:
            db.commit()
            db.refresh(product)
        else:
            db.flush()
        return product

    @staticmethod
    def get_user_products(
        db: Session,
        user_id: str,
        params: PaginationParams,
    ) -> dict:
        generation_counts = _generation_count_subquery(db)
        base = (
            db.query(
                Product,
                func.coalesce(generation_counts.c.generations_count, 0).label("generations_count"),
            )
            .join(Project)
            .outerjoin(generation_counts, Product.id == generation_counts.c.product_id)
            .filter(Project.user_id == user_id)
        )

        total = base.order_by(None).count()
        rows = (
            _apply_product_sort(base, params)
            .offset((params.page - 1) * params.page_size)
            .limit(params.page_size)
            .all()
        )

        items = [
            {
                "id": str(product.id),
                "project_id": str(product.project_id),
                "name": product.name,
                "category": product.category,
                "platform": product.platform,
                "market": product.market,
                "created_at": product.created_at.isoformat(),
                "generations_count": int(generations_count),
            }
            for product, generations_count in rows
        ]
        return paginate_dict(items, params.page, params.page_size, total)

    @staticmethod
    def get_by_id(
        db: Session,
        product_id: str,
        user_id: str,
    ) -> Product | None:
        try:
            product_uuid = uuid.UUID(product_id)
        except ValueError:
            return None

        return (
            db.query(Product)
            .join(Project)
            .filter(
                Product.id == product_uuid,
                Product.user_id == uuid.UUID(str(user_id)),
                Project.user_id == uuid.UUID(str(user_id)),
            )
            .first()
        )

    @staticmethod
    def delete(
        db: Session,
        product: Product,
    ) -> None:
        db.delete(product)
        db.commit()

    @staticmethod
    def get_generations(
        db: Session,
        product_id: uuid.UUID,
    ) -> list[Generation]:
        return (
            db.query(Generation)
            .filter(Generation.product_id == product_id)
            .order_by(Generation.created_at.desc())
            .all()
        )

    @staticmethod
    def serialize_product(
        product: Product,
    ):
        return {
            "id": str(product.id),
            "project_id": str(product.project_id),
            "name": product.name,
            "category": product.category,
            "platform": product.platform,
            "market": product.market,
            "target_customer": product.target_customer,
            "advantages": product.advantages,
            "created_at": product.created_at.isoformat() if product.created_at else None,
        }

    @staticmethod
    def get_detail(
        db: Session,
        product: Product,
    ) -> dict:
        product_id = orm_uuid(product.id)
        stats_row = (
            db.query(
                func.count(Generation.id).label("total_generations"),
                func.max(Generation.created_at).label("last_generated"),
            )
            .filter(Generation.product_id == product_id)
            .one()
        )
        type_rows = (
            db.query(Generation.type, func.count(Generation.id))
            .filter(Generation.product_id == product_id)
            .group_by(Generation.type)
            .all()
        )
        generation_types = {str(gtype): int(count) for gtype, count in type_rows}

        generations = ProductService.get_generations(db, product_id)
        stats = {
            "total_generations": int(stats_row.total_generations or 0),
            "last_generated": stats_row.last_generated.isoformat()
            if stats_row.last_generated
            else None,
            "generation_types": generation_types,
        }

        project = product.project
        latest_listing = next((g for g in generations if g.type == "listing"), None)
        score = None
        if latest_listing:
            output: dict = orm_dict(latest_listing.output) if latest_listing.output else {}
            score = output.get("score") or compute_listing_score(output)

        next_actions = build_next_actions(score, generation_types)

        return {
            "id": str(product.id),
            "project_id": str(product.project_id),
            "name": product.name,
            "category": product.category,
            "platform": product.platform,
            "market": product.market,
            "target_customer": product.target_customer,
            "advantages": product.advantages,
            "created_at": product.created_at.isoformat() if product.created_at else None,
            "project": {"id": str(project.id), "name": project.name} if project else None,
            "stats": stats,
            "score": score,
            "next_actions": next_actions,
            "generations": [
                {
                    "id": str(g.id),
                    "type": g.type,
                    "input": g.input,
                    "output": g.output,
                    "tokens_used": g.tokens_used,
                    "created_at": g.created_at.isoformat(),
                }
                for g in generations
            ],
        }

    @staticmethod
    def resolve_or_create(
        db: Session,
        user_id: str,
        project_id: str,
        product_id: str | None,
        name: str,
        category: str,
        platform: str,
        market: str,
        target_customer: str | None = None,
        advantages: list[str] | None = None,
        *,
        commit: bool = True,
    ) -> uuid.UUID:
        if product_id:
            try:
                product_uuid = uuid.UUID(str(product_id))
                owner_uuid = uuid.UUID(str(user_id))

                product = (
                    db.query(Product)
                    .join(Project)
                    .filter(
                        Product.id == product_uuid,
                        Product.user_id == owner_uuid,
                        Project.id == project_id,
                        Project.user_id == owner_uuid,
                    )
                    .first()
                )

                if product:
                    updated = False
                    if target_customer and target_customer != product.target_customer:
                        product.target_customer = target_customer  # type: ignore[assignment]
                        updated = True
                    if advantages:
                        product.advantages = advantages  # type: ignore[assignment]
                        updated = True
                    if updated:
                        db.add(product)
                        if commit:
                            db.commit()
                            db.refresh(product)
                        else:
                            db.flush()
                    return uuid.UUID(str(product.id))
            except ValueError:
                pass

        product = ProductService.create(
            db=db,
            user_id=user_id,
            project_id=project_id,
            name=name,
            category=category,
            platform=platform,
            market=market,
            target_customer=target_customer,
            advantages=advantages,
            commit=commit,
        )
        return uuid.UUID(str(product.id))
