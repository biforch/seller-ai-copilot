import uuid

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.generation import Generation
from app.models.product import Product
from app.models.project import Project
from app.services.scoring import compute_listing_score, build_next_actions



class ProductService:
    """商品业务逻辑."""



    @staticmethod
    def create(
        db: Session,
        user_id: str,
        project_id: str,
        name: str,
        category: Optional[str] = None,
        platform: str = "Amazon",
        market: str = "USA",
        target_customer: Optional[str] = None,
        advantages: Optional[List[str]] = None,
    ) -> Product:


        project = (
            db.query(Project)
            .filter(
                Project.id == project_id,
                Project.user_id == user_id,
            )
            .first()
        )


        if not project:
            raise ValueError(
                "Project not found"
            )


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

        db.commit()

        db.refresh(product)


        return product




    @staticmethod
    def get_user_products(
        db: Session,
        user_id: str,
    ) -> List[dict]:


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
    ) -> Optional[Product]:


        try:

            product_uuid = uuid.UUID(product_id)


        except ValueError:

            return None



        return (
            db.query(Product)
            .join(Project)
            .filter(
                Product.id == product_uuid,

                Project.user_id == user_id,
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
    ) -> List[Generation]:


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
            product.id,
        )


        generation_types = {}

        for g in generations:

            generation_types[g.type] = (
                generation_types.get(g.type, 0) + 1
            )


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

            output = latest_listing.output or {}

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
        product_id: Optional[str],
        name: str,
        category: str,
        platform: str,
        market: str,
        target_customer: Optional[str] = None,
        advantages: Optional[List[str]] = None,
    ) -> uuid.UUID:
        """
        查找当前 Project 下已有 Product，
        不存在则创建。
        若提供了新的 target_customer/advantages，
        更新到已有 Product 上，使其持续累积上下文。
        """



        if product_id:


            try:

                product_uuid = uuid.UUID(product_id)


                product = (
                    db.query(Product)
                    .join(Project)
                    .filter(
                        Product.id == product_uuid,

                        Project.id == project_id
                    )
                    .first()
                )


                if product:

                    updated = False

                    if target_customer and target_customer != product.target_customer:

                        product.target_customer = target_customer

                        updated = True

                    if advantages:

                        product.advantages = advantages

                        updated = True

                    if updated:

                        db.add(product)

                        db.commit()

                        db.refresh(product)

                    return product.id



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
        )


        return product.id