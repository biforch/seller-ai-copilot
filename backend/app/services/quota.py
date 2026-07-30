import logging

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


QUOTA_PERIOD_DAYS = 30



def reset_monthly_quota(
    user,
    db: Session,
):
    """
    检查是否需要30天周期重置
    """


    now = datetime.utcnow()


    # 第一次初始化额度周期
    if user.reset_date is None:

        user.reset_date = (
            now +
            timedelta(
                days=QUOTA_PERIOD_DAYS
            )
        )


        db.add(user)
        db.commit()
        db.refresh(user)


        logger.info(
            "Initialize quota reset date user=%s reset=%s",
            user.email,
            user.reset_date,
        )


        return



    # 到期重置
    if now >= user.reset_date:

        logger.info(
            "Reset monthly quota user=%s",
            user.email,
        )


        user.used_tokens = 0


        user.reset_date = (
            now +
            timedelta(
                days=QUOTA_PERIOD_DAYS
            )
        )


        db.add(user)
        db.commit()
        db.refresh(user)



def check_quota(
    user,
    db: Session,
):
    """
    检查用户剩余额度
    """


    reset_monthly_quota(
        user,
        db,
    )


    remaining = (
        user.monthly_tokens
        -
        user.used_tokens
    )


    logger.info(
        "Quota check user=%s used=%s total=%s remaining=%s",
        user.email,
        user.used_tokens,
        user.monthly_tokens,
        remaining,
    )


    if remaining <= 0:

        raise HTTPException(
            status_code=403,
            detail=(
                "AI quota exceeded. "
                "Please upgrade your plan."
            )
        )


    return remaining



def consume_tokens(
    user,
    tokens: int,
    db: Session,
):
    """
    扣除token额度
    """


    if tokens <= 0:
        return


    logger.info(
        "Consume tokens user=%s tokens=%s before_used=%s",
        user.email,
        tokens,
        user.used_tokens,
    )


    user.used_tokens += tokens


    db.add(user)

    db.commit()

    db.refresh(user)


    logger.info(
        "Consume tokens success user=%s after_used=%s",
        user.email,
        user.used_tokens,
    )