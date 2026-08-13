import uuid

from sqlalchemy.orm import Session

from app.models.generation import Generation
from app.models.product import Product
from app.models.project import Project


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
    ) -> list[dict]:



        projects = (

            db.query(Project)

            .filter(

                Project.user_id == user_id

            )

            .order_by(

                Project.created_at.desc()

            )

            .all()

        )



        result=[]



        for project in projects:


            product_count = (

                db.query(Product)

                .filter(

                    Product.project_id == project.id

                )

                .count()

            )



            result.append({

                "id":str(project.id),

                "name":project.name,

                "description":project.description,

                "platform":project.platform,

                "market":project.market,

                "status":project.status,

                "product_count":product_count,

                "created_at":
                    project.created_at.isoformat(),

            })


        return result




    @staticmethod
    def get_project_detail(
        db: Session,
        project_id: str,
        user_id,
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


        products = (

            db.query(Product)

            .filter(

                Product.project_id == project.id

            )

            .order_by(

                Product.created_at.desc()

            )

            .all()

        )


        product_list = []


        for p in products:

            generations_count = (

                db.query(Generation)

                .filter(

                    Generation.product_id == p.id

                )

                .count()

            )

            product_list.append({

                "id": str(p.id),

                "name": p.name,

                "category": p.category,

                "platform": p.platform,

                "market": p.market,

                "generations_count": generations_count,

                "created_at": p.created_at.isoformat(),

            })


        return {

            "id": str(project.id),

            "name": project.name,

            "description": project.description,

            "platform": project.platform,

            "market": project.market,

            "status": project.status,

            "product_count": len(product_list),

            "created_at": project.created_at.isoformat(),

            "updated_at": project.updated_at.isoformat(),

            "products": product_list,

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