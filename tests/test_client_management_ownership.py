"""Service-level ownership check tests for ClientManagement's clinic-scoping
guard (_ensure_client_in_clinic / get_client_by_id's linkage check).

docs: cross-clinic IDOR fix - every client-lookup/edit/delete/name-change
method on ClientManagement must reject a client_id that is not linked to the
acting admin's clinic via the client_clinics many-to-many table, and must
fail closed (reject, not silently allow) if the ClientClinicRepository was
never wired in.

Follows the direct-service-construction style of test_client_management.py
(not the router/_find_handler style of test_appointment_browser_ownership.py,
since these are service-level checks, not per-handler wiring checks).
"""

import pytest

from bot.exceptions.user_exceptions import UserNotFoundError
from bot.models.user import User
from bot.services.client.client_management import ClientManagement
from bot.utils.role import Role


CLINIC_A = 1
CLINIC_B = 2
CLINIC_C = 3


def _client(user_id=1, full_name="Ivanov Ivan", phone="+998901234567"):
    return User(ID=user_id, full_name=full_name, phone=phone, role=Role.CLIENT)


def _service(user_repo, client_clinic_repo):
    return ClientManagement(
        user_repository=user_repo,
        staff_repository=None,
        clinic_repository=None,
        client_clinic_repository=client_clinic_repo,
    )


# --- get_client_by_id ---

@pytest.mark.asyncio
async def test_get_client_by_id_returns_client_when_linked(fake_user_repo_factory, fake_client_clinic_repo_factory):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_A)})
    service = _service(user_repo, client_clinic_repo)

    result = await service.get_client_by_id(1, CLINIC_A)

    assert result is client


@pytest.mark.asyncio
async def test_get_client_by_id_returns_none_when_not_linked(fake_user_repo_factory, fake_client_clinic_repo_factory):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_B)})
    service = _service(user_repo, client_clinic_repo)

    result = await service.get_client_by_id(1, CLINIC_A)

    assert result is None


@pytest.mark.asyncio
async def test_get_client_by_id_returns_none_when_client_does_not_exist(
    fake_user_repo_factory, fake_client_clinic_repo_factory,
):
    user_repo = fake_user_repo_factory()
    client_clinic_repo = fake_client_clinic_repo_factory()
    service = _service(user_repo, client_clinic_repo)

    result = await service.get_client_by_id(999, CLINIC_A)

    assert result is None


@pytest.mark.asyncio
async def test_get_client_by_id_not_linked_and_nonexistent_are_indistinguishable(
    fake_user_repo_factory, fake_client_clinic_repo_factory,
):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_B)})
    service = _service(user_repo, client_clinic_repo)

    not_linked_result = await service.get_client_by_id(1, CLINIC_A)
    nonexistent_result = await service.get_client_by_id(999, CLINIC_A)

    assert not_linked_result is None
    assert nonexistent_result is None
    assert not_linked_result == nonexistent_result


# --- delete_client ---

@pytest.mark.asyncio
async def test_delete_client_last_linked_clinic_unlinks_and_hard_deletes(
    fake_user_repo_factory, fake_client_clinic_repo_factory,
):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_A)})
    service = _service(user_repo, client_clinic_repo)

    result = await service.delete_client(1, CLINIC_A)

    assert result is True
    assert client_clinic_repo.unlinked_calls == [(1, CLINIC_A)]
    assert user_repo.deleted_clients == [1]


@pytest.mark.asyncio
async def test_delete_client_with_multiple_clinics_only_unlinks_requested_clinic(
    fake_user_repo_factory, fake_client_clinic_repo_factory,
):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_A), (1, CLINIC_B)})
    service = _service(user_repo, client_clinic_repo)

    result = await service.delete_client(1, CLINIC_A)

    assert result is False
    assert client_clinic_repo.unlinked_calls == [(1, CLINIC_A)]
    assert user_repo.deleted_clients == []
    assert await client_clinic_repo.client_linked_to_clinic(1, CLINIC_B) is True
    assert await client_clinic_repo.client_linked_to_clinic(1, CLINIC_A) is False


@pytest.mark.asyncio
async def test_delete_client_denies_admin_not_linked_to_client_clinic(
    fake_user_repo_factory, fake_client_clinic_repo_factory,
):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_A), (1, CLINIC_B)})
    service = _service(user_repo, client_clinic_repo)

    with pytest.raises(UserNotFoundError):
        await service.delete_client(1, CLINIC_C)

    assert client_clinic_repo.unlinked_calls == []
    assert user_repo.deleted_clients == []


# --- update_client_name / update_client_phone ---

@pytest.mark.asyncio
async def test_update_client_name_succeeds_for_linked_admin(fake_user_repo_factory, fake_client_clinic_repo_factory):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_A)})
    service = _service(user_repo, client_clinic_repo)

    updated = await service.update_client_name(1, "Петров Петр", CLINIC_A)

    assert updated.full_name == "Петров Петр"
    assert user_repo.updated_clients == [(1, updated)]


@pytest.mark.asyncio
async def test_update_client_name_denies_unlinked_admin_before_any_mutation(
    fake_user_repo_factory, fake_client_clinic_repo_factory,
):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_B)})
    service = _service(user_repo, client_clinic_repo)

    with pytest.raises(UserNotFoundError):
        await service.update_client_name(1, "Петров Петр", CLINIC_A)

    assert user_repo.updated_clients == []
    assert client.full_name == "Ivanov Ivan"


@pytest.mark.asyncio
async def test_update_client_phone_succeeds_for_linked_admin(fake_user_repo_factory, fake_client_clinic_repo_factory):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_A)})
    service = _service(user_repo, client_clinic_repo)

    updated = await service.update_client_phone(1, "998907654321", CLINIC_A)

    assert updated.phone == "+998907654321"
    assert user_repo.updated_clients == [(1, updated)]


@pytest.mark.asyncio
async def test_update_client_phone_denies_unlinked_admin_before_any_mutation(
    fake_user_repo_factory, fake_client_clinic_repo_factory,
):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_B)})
    service = _service(user_repo, client_clinic_repo)

    with pytest.raises(UserNotFoundError):
        await service.update_client_phone(1, "998907654321", CLINIC_A)

    assert user_repo.updated_clients == []
    assert client.phone == "+998901234567"


# --- approve_name_change / reject_name_change ---

@pytest.mark.asyncio
async def test_approve_name_change_succeeds_for_linked_admin(fake_user_repo_factory, fake_client_clinic_repo_factory):
    client = _client()
    client.pending_full_name = "Petrov Petr"
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_A)})
    service = _service(user_repo, client_clinic_repo)

    result = await service.approve_name_change(1, CLINIC_A)

    assert result.full_name == "Petrov Petr"
    assert result.pending_full_name is None


@pytest.mark.asyncio
async def test_approve_name_change_denies_unlinked_admin(fake_user_repo_factory, fake_client_clinic_repo_factory):
    client = _client()
    client.pending_full_name = "Petrov Petr"
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_B)})
    service = _service(user_repo, client_clinic_repo)

    with pytest.raises(UserNotFoundError):
        await service.approve_name_change(1, CLINIC_A)

    assert client.pending_full_name == "Petrov Petr"
    assert client.full_name == "Ivanov Ivan"


@pytest.mark.asyncio
async def test_reject_name_change_succeeds_for_linked_admin(fake_user_repo_factory, fake_client_clinic_repo_factory):
    client = _client()
    client.pending_full_name = "Petrov Petr"
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_A)})
    service = _service(user_repo, client_clinic_repo)

    result = await service.reject_name_change(1, CLINIC_A)

    assert result.full_name == "Ivanov Ivan"
    assert result.pending_full_name is None


@pytest.mark.asyncio
async def test_reject_name_change_denies_unlinked_admin(fake_user_repo_factory, fake_client_clinic_repo_factory):
    client = _client()
    client.pending_full_name = "Petrov Petr"
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, CLINIC_B)})
    service = _service(user_repo, client_clinic_repo)

    with pytest.raises(UserNotFoundError):
        await service.reject_name_change(1, CLINIC_A)

    assert client.pending_full_name == "Petrov Petr"


# --- Fail closed: client_clinic_repository=None must reject, never silently allow ---
#
# This is the regression that would have caught a "forgot to wire DI"
# mistake in production (e.g. a router factory constructed without its
# client_clinic_repo argument): with the collaborator missing entirely, every
# clinic-scoped method must behave as if the client had no linkage at all,
# not skip the check.

@pytest.mark.asyncio
async def test_get_client_by_id_fails_closed_without_client_clinic_repository(fake_user_repo_factory):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    service = _service(user_repo, client_clinic_repo=None)

    result = await service.get_client_by_id(1, CLINIC_A)

    assert result is None


@pytest.mark.asyncio
async def test_delete_client_fails_closed_without_client_clinic_repository(fake_user_repo_factory):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    service = _service(user_repo, client_clinic_repo=None)

    with pytest.raises(UserNotFoundError):
        await service.delete_client(1, CLINIC_A)

    assert user_repo.deleted_clients == []


@pytest.mark.asyncio
async def test_update_client_name_fails_closed_without_client_clinic_repository(fake_user_repo_factory):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    service = _service(user_repo, client_clinic_repo=None)

    with pytest.raises(UserNotFoundError):
        await service.update_client_name(1, "Петров Петр", CLINIC_A)

    assert user_repo.updated_clients == []


@pytest.mark.asyncio
async def test_update_client_phone_fails_closed_without_client_clinic_repository(fake_user_repo_factory):
    client = _client()
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    service = _service(user_repo, client_clinic_repo=None)

    with pytest.raises(UserNotFoundError):
        await service.update_client_phone(1, "998907654321", CLINIC_A)

    assert user_repo.updated_clients == []


@pytest.mark.asyncio
async def test_approve_name_change_fails_closed_without_client_clinic_repository(fake_user_repo_factory):
    client = _client()
    client.pending_full_name = "Petrov Petr"
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    service = _service(user_repo, client_clinic_repo=None)

    with pytest.raises(UserNotFoundError):
        await service.approve_name_change(1, CLINIC_A)

    assert client.pending_full_name == "Petrov Petr"


@pytest.mark.asyncio
async def test_reject_name_change_fails_closed_without_client_clinic_repository(fake_user_repo_factory):
    client = _client()
    client.pending_full_name = "Petrov Petr"
    user_repo = fake_user_repo_factory(clients_by_id={1: client})
    service = _service(user_repo, client_clinic_repo=None)

    with pytest.raises(UserNotFoundError):
        await service.reject_name_change(1, CLINIC_A)

    assert client.pending_full_name == "Petrov Petr"
