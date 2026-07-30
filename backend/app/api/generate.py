import logging

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.rate_limit import limiter
from app.core.response import success_response
from app.core.security import get_current_user
from app.database.session import get_db

from app.models.generation import Generation
from app.models.user import User
from app.models.project import Project

from app.schemas.generate import (
    AnalyzeRequest,
    GenerateListingRequest,
)

from app.services.analyzer import AnalyzerService
from app.services.openai import OpenAIService
from app.services.product import ProductService
from app.services.scoring import compute_listing_score

from app.services.quota import check_quota


router = APIRouter()

logger = logging.getLogger(__name__)


def get_user(
    db: Session,
    user_id: str,
):

    user = (
        db.query(User)
        .filter(
            User.id == user_id
        )
        .first()
    )

    if not user:

        raise AppException(
            message="User not found",
            code=status.HTTP_404_NOT_FOUND,
        )

    return user



def get_project(
    db: Session,
    project_id,
    user_id,
):

    if not project_id:
        return None


    project = (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.user_id == user_id,
        )
        .first()
    )


    if not project:

        raise AppException(
            message="Project not found",
            code=status.HTTP_404_NOT_FOUND,
        )


    return project




def resolve_context(
    db: Session,
    user_id,
    product_id,
    target_customer,
    advantages,
):
    """
    未在本次请求中提供 target_customer/advantages 时，
    沿用该 Product 上已保存的上下文。
    """

    if target_customer and advantages:
        return target_customer, advantages


    if not product_id:
        return target_customer, advantages


    existing = ProductService.get_by_id(
        db,
        product_id,
        user_id,
    )

    if not existing:
        return target_customer, advantages

    return (
        target_customer or existing.target_customer,
        advantages or existing.advantages,
    )




def save_generation(
    db: Session,
    user: User,
    project_id=None,
    product_id=None,
    generation_type="",
    input_data=None,
    output_data=None,
    tokens_used=0,
):

    generation = Generation(

        user_id=user.id,

        project_id=project_id,

        product_id=product_id,

        type=generation_type,

        input=input_data or {},

        output=output_data or {},

        tokens_used=tokens_used,

    )


    user.used_tokens += tokens_used


    db.add(generation)

    db.add(user)


    db.commit()


    db.refresh(generation)

    db.refresh(user)


    return generation





@router.post("/listing")
@limiter.limit("20/hour")
async def generate_listing(
    request: Request,
    body: GenerateListingRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    try:

        user = get_user(
            db,
            current_user["id"],
        )


        project = get_project(
            db,
            body.project_id,
            user.id,
        )


        check_quota(
            user,
            db
        )


        target_customer, advantages = resolve_context(
            db=db,
            user_id=user.id,
            product_id=body.product_id,
            target_customer=body.target_customer,
            advantages=body.advantages,
        )


        ai_service = OpenAIService()


        result = await ai_service.generate_listing(
            product_name=body.name,
            category=body.category,
            market=body.market,
            platform=body.platform,
            project_goal=project.description if project else None,
            target_customer=target_customer,
            advantages=advantages,
        )


        tokens_used = result.get(
            "tokens_used",
            0,
        )


        score = compute_listing_score(result)

        result_with_score = {
            **result,
            "score": score,
        }


        product_id = ProductService.resolve_or_create(
            db=db,
            user_id=user.id,
            project_id=project.id,
            product_id=body.product_id,
            name=body.name,
            category=body.category,
            platform=body.platform,
            market=body.market,
            target_customer=target_customer,
            advantages=advantages,
        )


        save_generation(
            db=db,
            user=user,

            project_id=project.id
            if project
            else None,

            product_id=product_id,

            generation_type="listing",

            input_data={
                "name": body.name,
                "category": body.category,
                "market": body.market,
                "platform": body.platform,
            },

            output_data=result_with_score,

            tokens_used=tokens_used,
        )



        return success_response(
            data={

                "project_id":
                    str(project.id)
                    if project
                    else None,

                "product_id":
                    str(product_id),

                "title":
                    result.get("title",""),

                "bullets":
                    result.get("bullets",[]),

                "description":
                    result.get("description",""),

                "keywords":
                    result.get("keywords",[]),

                "score":
                    score,

                "tokens_used":
                    tokens_used,
            }
        )


    except AppException:

        raise


    except Exception as e:

        logger.exception(
            "Generate listing failed"
        )


        raise AppException(
            message="AI generation failed",
            code=500,
            detail=str(e),
            cause=e,
        ) from e





@router.post("/analyze")
@limiter.limit("20/hour")
async def analyze_listing(
    request: Request,
    body: AnalyzeRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    try:

        user = get_user(
            db,
            current_user["id"],
        )


        project = get_project(
            db,
            body.project_id,
            user.id,
        )


        check_quota(
            user,
            db
        )


        analyzer = AnalyzerService()


        result = await analyzer.analyze_listing(
            title=body.title,
            reviews=body.reviews,
            rating=body.rating,
            description=body.description,
        )


        tokens_used = result.get(
            "tokens_used",
            0,
        )


        save_generation(
            db=db,
            user=user,

            project_id=
                project.id
                if project
                else None,

            product_id=None,

            generation_type="analysis",

            input_data={
                "title": body.title,
                "reviews": body.reviews,
                "rating": body.rating,
                "description": body.description,
            },

            output_data=result,

            tokens_used=tokens_used,
        )


        return success_response(
            data={
                **result,

                "project_id":
                    str(project.id)
                    if project
                    else None,

                "tokens_used":
                    tokens_used,
            }
        )


    except AppException:

        raise


    except Exception as e:

        logger.exception(
            "Analyze failed"
        )


        raise AppException(
            message="Analysis failed",
            code=500,
            detail=str(e),
            cause=e,
        ) from e





@router.post("/keywords")
@limiter.limit("20/hour")
async def generate_keywords(
    request: Request,
    body: GenerateListingRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    try:

        user = get_user(
            db,
            current_user["id"],
        )


        project = get_project(
            db,
            body.project_id,
            user.id,
        )


        check_quota(
            user,
            db
        )


        target_customer, advantages = resolve_context(
            db=db,
            user_id=user.id,
            product_id=body.product_id,
            target_customer=body.target_customer,
            advantages=body.advantages,
        )


        ai_service = OpenAIService()


        result = await ai_service.generate_keywords(
            product_name=body.name,
            category=body.category,
            market=body.market,
            target_customer=target_customer,
            advantages=advantages,
        )


        tokens_used = result.get(
            "tokens_used",
            0,
        )


        product_id = ProductService.resolve_or_create(
            db=db,
            user_id=user.id,
            project_id=project.id,
            product_id=body.product_id,
            name=body.name,
            category=body.category,
            platform=body.platform,
            market=body.market,
            target_customer=target_customer,
            advantages=advantages,
        )


        save_generation(
            db=db,
            user=user,

            project_id=
                project.id
                if project
                else None,

            product_id=product_id,

            generation_type="keywords",

            input_data={
                "name": body.name,
                "category": body.category,
                "market": body.market,
            },

            output_data=result,

            tokens_used=tokens_used,
        )


        return success_response(
            data={
                **result,

                "project_id":
                    str(project.id)
                    if project
                    else None,

                "product_id":
                    str(product_id),

                "tokens_used":
                    tokens_used,
            }
        )


    except AppException:

        raise


    except Exception as e:

        logger.exception(
            "Generate keywords failed"
        )


        raise AppException(
            message="Keyword generation failed",
            code=500,
            detail=str(e),
            cause=e,
        ) from e