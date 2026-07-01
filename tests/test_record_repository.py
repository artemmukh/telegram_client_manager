import pytest
import pytest_asyncio

from bot.models.record import Record
from bot.models.user import User
from bot.repositories.records_repository import RecordRepository
from bot.repositories.user_repository import UserRepository
from bot.utils.role import Role


@pytest_asyncio.fixture
async def record_repo_setup(tmp_path):
    db_path = tmp_path / "test.db"
    user_repo = UserRepository(str(db_path))
    record_repo = RecordRepository(str(db_path))
    await user_repo.init()
    await record_repo.init()
    await user_repo.create_user(
        User(
            full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
            phone="+998901234567",
            role=Role.CLIENT,
            telegram_user_id=1001,
        )
    )
    user = await user_repo.get_user_by_telegram_id(1001)
    return record_repo, user


@pytest.mark.asyncio
async def test_record_repository_creates_and_reads_record(record_repo_setup):
    record_repo, user = record_repo_setup
    record = Record(
        user_id=user.ID,
        date_time="2026-07-01 10:00",
        description="Consultation",
        recommendation="Follow up",
        price=150.0,
        status="scheduled",
    )

    await record_repo.create_record(record)
    records = await record_repo.get_records_by_user_id(user.ID)
    by_telegram_id = await record_repo.get_records_by_telegram_id(1001)
    by_id = await record_repo.get_record_by_id(records[0].primary_id)

    assert len(records) == 1
    assert records[0].description == "Consultation"
    assert records[0].price == 150.0
    assert by_telegram_id == records
    assert by_id == records[0]
    assert await record_repo.record_exists(records[0].primary_id) is True


@pytest.mark.asyncio
async def test_record_repository_updates_record(record_repo_setup):
    record_repo, user = record_repo_setup
    await record_repo.create_record(
        Record(
            user_id=user.ID,
            date_time="2026-07-01 10:00",
            description="Consultation",
            recommendation="Follow up",
            price=150.0,
            status="scheduled",
        )
    )
    record_id = (await record_repo.get_records_by_user_id(user.ID))[0].primary_id

    await record_repo.update_record(
        record_id,
        Record(
            user_id=user.ID,
            date_time="2026-07-02 11:30",
            description="Updated consultation",
            recommendation="Updated follow up",
            price=200.0,
            status="done",
        ),
    )

    updated = await record_repo.get_record_by_id(record_id)

    assert updated.date_time == "2026-07-02 11:30"
    assert updated.description == "Updated consultation"
    assert updated.recommendation == "Updated follow up"
    assert updated.price == 200.0
    assert updated.status == "done"


@pytest.mark.asyncio
async def test_record_repository_deletes_record(record_repo_setup):
    record_repo, user = record_repo_setup
    await record_repo.create_record(
        Record(
            user_id=user.ID,
            date_time="2026-07-01 10:00",
            description="Consultation",
            recommendation="Follow up",
            price=150.0,
            status="scheduled",
        )
    )
    record_id = (await record_repo.get_records_by_user_id(user.ID))[0].primary_id

    await record_repo.delete_record(record_id)

    assert await record_repo.get_record_by_id(record_id) is None
    assert await record_repo.record_exists(record_id) is False
