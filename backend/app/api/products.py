from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.response import success_response
from app.core.security import get_current_user
from app.database.session import get_db

from app.schemas.product import CreateProductRequest

from app.services.product import ProductService



router = APIRouter()





@router.post("")
async def create_product(

    request: CreateProductRequest,

    current_user: dict = Depends(get_current_user),

    db: Session = Depends(get_db),

):


    product = ProductService.create(

        db=db,

        user_id=current_user["id"],

        project_id=request.project_id,

        name=request.name,

        category=request.category,

        platform=request.platform,

        market=request.market,

    )



    return success_response(

        data=ProductService.serialize_product(product),

        message="Product created successfully",

        code=201,

    )







@router.get("")
async def get_products(

    current_user: dict = Depends(get_current_user),

    db: Session = Depends(get_db),

):


    products = ProductService.get_user_products(

        db,

        current_user["id"]

    )


    return success_response(

        data=products

    )








@router.get("/{product_id}")
async def get_product(

    product_id: str,

    current_user: dict = Depends(get_current_user),

    db: Session = Depends(get_db),

):


    product = ProductService.get_by_id(

        db,

        product_id,

        current_user["id"]

    )



    if not product:

        raise AppException(

            "Product not found",

            status.HTTP_404_NOT_FOUND

        )



    return success_response(

        data=ProductService.get_detail(

            db,

            product

        )

    )







@router.delete("/{product_id}")
async def delete_product(

    product_id: str,

    current_user: dict = Depends(get_current_user),

    db: Session = Depends(get_db),

):


    product = ProductService.get_by_id(

        db,

        product_id,

        current_user["id"]

    )


    if not product:

        raise AppException(

            "Product not found",

            status.HTTP_404_NOT_FOUND

        )


    ProductService.delete(

        db,

        product

    )


    return success_response(

        message="Product deleted successfully"

    )