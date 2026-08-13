import uuid

from sqlalchemy.orm import Session

from app.core.orm_utils import orm_dict, orm_uuid
from app.models.generation import Generation
from app.models.product import Product
from app.models.project import Project
from app.services.scoring import build_next_actions, compute_listing_score


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
    ) -> list[dict]:


        products = (
            db.query(Product)
            .join(Project)
            .filter(
                Project.user_id == user_id
            )
            .order_by(
                Product.created_at.desc()
            )
            .all()
        )


        result = []


        for p in products:


            generations_count = (
                db.query(Generation)
                .filter(
                    Generation.product_id == p.id
                )
                .count()
            )


            result.append(
                {
                    "id": str(p.id),

                    "project_id": str(p.project_id),

                    "name": p.name,

                    "category": p.category,

                    "platform": p.platform,

                    "market": p.market,

                    "created_at": p.created_at.isoformat(),

                    "generations_count": generations_count,
                }
            )


        return result





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
            .filter(
                Generation.product_id == product_id
            )
            .order_by(
                Generation.created_at.desc()
            )
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

            "created_at":
                product.created_at.isoformat()
                if product.created_at
                else None,
        }



    @staticmethod
    def get_detail(
        db: Session,
        product: Product,
    ) -> dict:

        generations = ProductService.get_generations(
            db,
            orm_uuid(product.id),
        )

        generation_types: dict[str, int] = {}

        for g in generations:
            gtype = str(g.type)
            generation_types[gtype] = generation_types.get(gtype, 0) + 1


        stats = {

            "total_generations": len(generations),

            "last_generated":
                generations[0].created_at.isoformat()
                if generations
                else None,

            "generation_types": generation_types,

        }


        project = product.project


        latest_listing = next(
            (g for g in generations if g.type == "listing"),
            None,
        )

        score = None

        if latest_listing:

            output: dict = orm_dict(latest_listing.output) if latest_listing.output else {}

            score = (
                output.get("score")
                or compute_listing_score(output)
            )


        next_actions = build_next_actions(
            score,
            generation_types,
        )


        return {

            "id": str(product.id),

            "project_id": str(product.project_id),

            "name": product.name,

            "category": product.category,

            "platform": product.platform,

            "market": product.market,

            "target_customer": product.target_customer,

            "advantages": product.advantages,

            "created_at":
                product.created_at.isoformat()
                if product.created_at
                else None,

            "project": {

                "id": str(project.id),

                "name": project.name,

            } if project else None,

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
        """
        查找当前 Project 下已有 Product，
        不存在则创建。
        若提供了新的 target_customer/advantages，
        更新到已有 Product 上，使其持续累积上下文。
        """



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

                        product.target_customer = target_customer  # type: ignore[assignment]  # SQLAlchemy Product legacy Column typing

                        updated = True

                    if advantages:

                        product.advantages = advantages  # type: ignore[assignment]  # SQLAlchemy Product legacy Column typing

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