from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.product import Product
from app.models.generation import Generation
from app.core.response import success_response


router = APIRouter()


@router.get("/usage")
async def get_usage(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    user = (
        db.query(User)
        .filter(
            User.id == current_user["id"]
        )
        .first()
    )


    if not user:
        return success_response(
            data={}
        )


    total_generations = (
        db.query(Generation)
        .join(
            Product,
            Generation.product_id == Product.id
        )
        .filter(
            Product.user_id == user.id
        )
        .count()
    )


    remaining = (
        user.monthly_tokens
        -
        user.used_tokens
    )


    usage_percent = (
        user.used_tokens
        /
        user.monthly_tokens
        *
        100
        if user.monthly_tokens > 0
        else 0
    )


    return success_response(
        data={
            "plan": user.plan,

            "monthly_tokens": user.monthly_tokens,

            "used_tokens": user.used_tokens,

            "remaining_tokens": remaining,

            "usage_percent": round(
                usage_percent,
                2,
            ),

            "total_generations": total_generations,
        }
    )