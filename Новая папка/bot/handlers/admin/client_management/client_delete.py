from aiogram import Router, F

from bot.services.client.client_management import ClientManagement


def create_admin_client_delete_router(user_repo):


    router = Router()

    cl_mng = ClientManagement(user_repo)


    @router.callback_query(F.data == "delete_client")
    async def delete_client():





    return router