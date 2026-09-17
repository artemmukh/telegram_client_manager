# ZB VPS deployment runbook

Дата актуальности: 2026-08-24.

Этот runbook описывает текущую форму деплоя ZB-экземпляра по проверенным файлам репозитория. Если документ и код расходятся, первичен код.

Главный инвариант:

- одновременно может работать только один polling-экземпляр для `BOT_TOKEN_ZB`;
- локальный `bot-zb` и облачный `bot-zb` не запускаются параллельно;
- для SQLite-баз не используется обычный `cp` живых файлов `*.db`, `*.db-wal`, `*.db-shm`;
- секреты, токены, OCID, ключи и содержимое `.env` не печатаются в терминал и не попадают в Git.

## Что уже подтверждено локально

- `compose.yaml` содержит только сервис `bot-zb`.
- Контейнер видит данные как `/app/data`.
- На хосте bind mount использует `/srv/medical-bot/data:/app/data`.
- Образ запускает `python -m deploy.container_entrypoint`.
- `deploy/container_entrypoint.py` сначала провиженит runtime assets из `/opt/runtime-seed` в `/app/data`, а затем запускает `bot.run`.
- `deploy/systemd/bot-zb.service` и `deploy/systemd/bot-zb-backup.service` уже описаны в репозитории.
- `deploy/backup_to_oci.py` работает через OCI Object Storage и instance principal.
- `deploy/snapshot_export.py`, `deploy/snapshot_verifier.py` и `deploy/restore_drill.py` уже дают безопасный export / verify / isolated restore путь.

Что не подтверждалось на этой Windows-машине:

- `docker compose config`, `docker compose build`, `docker compose up`, `docker compose logs`;
- `systemd-analyze verify`, `systemctl enable`, `systemctl start`;
- `oci os ns get --auth instance_principal` и реальная загрузка в bucket.

## Роли путей

| Слой | Путь |
|---|---|
| Репозиторий на VM | `/opt/telegram_client_manager` |
| Данные на хосте | `/srv/medical-bot/data` |
| Данные в контейнере | `/app/data` |
| Seed runtime assets в образе | `/opt/runtime-seed` |
| ZB env для compose | `deploy/zb.env` |
| OCI backup env | `deploy/oci-backup.env` |
| systemd units | `deploy/systemd/bot-zb.service`, `deploy/systemd/bot-zb-backup.service`, `deploy/systemd/bot-zb-backup.timer` |

## Требования к окружению

- VM: Ubuntu 24.04 ARM64.
- Python: 3.11 или новее на хосте.
- Docker Engine и Compose v2.
- OCI CLI доступен на VM.
- Для backup service должен успешно проходить `python3 -m deploy.backup_to_oci --data-root /srv/medical-bot/data`.

Текущие checked-in файлы фиксируют такие значения:

- compose задаёт `BOT_INSTANCE=zb`;
- compose задаёт `DATA_BASE=/app/data/zb.db`;
- `deploy/zb.env.example` хранит placeholder-значения и non-secret settings для ZB;
- `deploy/oci-backup.env.example` хранит placeholder-значения и non-secret settings для OCI backup.

## Порядок работ

### 1. Подготовить Windows-экспорт без секретов

На Windows используй только локальные абсолютные пути. `source_generated_root` должен быть абсолютным Windows-путём в `PureWindowsPath`, который совпадает с путём, зашитым в SQLite-строках. Реальные пути и секреты не печатай.

```python
from pathlib import Path, PureWindowsPath

from deploy.snapshot_export import SnapshotRequest, dry_run_snapshot, export_snapshot

request = SnapshotRequest(
    main_db=Path(r"C:\LOCAL\medical-bot\data\zb.db"),
    reminders_db=Path(r"C:\LOCAL\medical-bot\data\reminders.db"),
    generated_root=Path(r"C:\LOCAL\medical-bot\data\history_of_illness\generated"),
    source_generated_root=PureWindowsPath(
        r"C:\LOCAL\medical-bot\data\history_of_illness\generated"
    ),
    output_dir=Path(r"C:\LOCAL\medical-bot\migration_export"),
)

dry_run_snapshot(request)
export_snapshot(request)
```

Что должно получиться:

- `migration_export/sqlite/main.db`;
- `migration_export/sqlite/reminders.db`;
- `migration_export/generated-medical-documents.tar`;
- `migration_export/metadata.json`;
- `migration_export/SHA256SUMS`;
- `migration_export/COMPLETE`.

Никакие исходные базы и документы не изменяются.

### 2. Передать экспорт на VM

С Windows отправляй только готовый экспорт.

```powershell
ssh -i <SSH_KEY> ubuntu@<VM_IP> "umask 077; install -d -m 700 /tmp/telegram-migration"
scp -i <SSH_KEY> -r C:\LOCAL\medical-bot\migration_export\* ubuntu@<VM_IP>:/tmp/telegram-migration/
ssh -i <SSH_KEY> ubuntu@<VM_IP> "chmod -R go-rwx /tmp/telegram-migration"
```

Не загружай экспорт в Telegram, Google Drive, GitHub или публичные bucket-ы.
На стороне VM transfer root уже должен существовать до `scp`; не создавай его после передачи.

### 3. Проверить экспорт на VM и разложить данные

Сначала проверить checksum-ы и только затем брать файлы в работу.

```bash
cd /tmp/telegram-migration
sha256sum -c SHA256SUMS
```

Затем сначала проверка, потом isolated restore в новый staging-root.

```bash
cd /opt/telegram_client_manager
umask 077
python3 - <<'PY'
from pathlib import Path

from deploy.restore_drill import restore_snapshot
from deploy.snapshot_verifier import verify_snapshot

snapshot = Path("/tmp/telegram-migration")
staging = Path("/tmp/telegram-staging")

if staging.exists():
    raise SystemExit("staging root already exists")

print(verify_snapshot(snapshot))
print(restore_snapshot(snapshot, staging))
PY
```

Этот шаг описывает только initial cutover. Если `/srv/medical-bot/data` уже существует и там есть данные, сначала нужен отдельный явно разрешённый restore-процедурный сценарий и свежий backup до любой замены.

Перед установкой убедись, что live data root пустой:

```bash
sudo sh -c 'if [ -d /srv/medical-bot/data ] && find /srv/medical-bot/data -mindepth 1 -print -quit | grep -q .; then exit 1; fi'
sudo install -d -o 10001 -g 10001 -m 700 /srv/medical-bot/data
sudo install -d -o 10001 -g 10001 -m 700 /srv/medical-bot/data/history_of_illness/generated
sudo chmod 700 /srv/medical-bot/data /srv/medical-bot/data/history_of_illness /srv/medical-bot/data/history_of_illness/generated
```

После этого install-им данные из staging:

```bash
cd /opt/telegram_client_manager
sudo install -o 10001 -g 10001 -m 600 /tmp/telegram-staging/sqlite/main.db /srv/medical-bot/data/zb.db
sudo install -o 10001 -g 10001 -m 600 /tmp/telegram-staging/sqlite/reminders.db /srv/medical-bot/data/reminders.db
sudo sh -c 'if [ -n "$(find /srv/medical-bot/data/history_of_illness/generated -mindepth 1 -print -quit)" ]; then echo "generated dir is not empty" >&2; exit 1; fi'
sudo cp -a /tmp/telegram-staging/generated-medical-documents/. /srv/medical-bot/data/history_of_illness/generated/
sudo chown -R 10001:10001 /srv/medical-bot/data
sudo find /srv/medical-bot/data -type d -exec chmod 700 {} \;
sudo find /srv/medical-bot/data -type f -exec chmod 600 {} \;
```

Такой порядок использует только офлайн-копии. Живые SQLite-файлы не копируются обычным `cp`.
`generated-medical-documents` берётся только из verifier-extracted staging, а не из raw `generated-medical-documents.tar`.

После install-ов проверь локальную целостность уже установленного live data:

```bash
sudo python3 - <<'PY'
import sqlite3
from pathlib import Path

for db_path in (
    Path("/srv/medical-bot/data/zb.db"),
    Path("/srv/medical-bot/data/reminders.db"),
):
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
PY
```

### 4. Провести локальный verify и isolated restore drill

Скачанный из Object Storage outer tar надо распаковывать только в новую staging-папку, затем проверять и восстанавливать только в изолированную директорию.

```bash
python3 - <<'PY'
from pathlib import Path
import tarfile
import shutil

EXPECTED = {
    "sqlite/main.db",
    "sqlite/reminders.db",
    "generated-medical-documents.tar",
    "metadata.json",
    "SHA256SUMS",
    "COMPLETE",
}

archive_path = Path("/tmp/telegram-restore/snapshot.tar")
incoming = Path("/tmp/telegram-restore/incoming")
drill = Path("/tmp/telegram-restore/drill")
if incoming.exists() or drill.exists():
    raise SystemExit("restore roots already exist")
incoming.mkdir(parents=True, exist_ok=False)

with tarfile.open(archive_path, "r:*") as archive:
    members = archive.getmembers()
    names = [member.name for member in members]
    if len(names) != 6 or set(names) != EXPECTED:
        raise SystemExit("unexpected snapshot tar layout")
    if len(set(names)) != len(names):
        raise SystemExit("duplicate snapshot tar members")
    for member in members:
        if not member.isreg():
            raise SystemExit("snapshot tar contains non-regular members")
        target = (incoming / member.name).resolve()
        if incoming.resolve() not in target.parents and target != incoming.resolve():
            raise SystemExit("snapshot tar traversal detected")
        target.parent.mkdir(parents=True, exist_ok=True)
        source = archive.extractfile(member)
        if source is None:
            raise SystemExit("snapshot tar member is unreadable")
        with source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination)
PY
python3 - <<'PY'
from pathlib import Path

from deploy.restore_drill import restore_snapshot
from deploy.snapshot_verifier import verify_snapshot

snapshot = Path("/tmp/telegram-restore/incoming")
drill = Path("/tmp/telegram-restore/drill")

print(verify_snapshot(snapshot))
print(restore_snapshot(snapshot, drill))
PY
```

The unique restore base `/tmp/telegram-restore` should be created with `umask 077` and mode `0700` before any file extraction, and both `incoming` and `drill` must be absent when the run starts. If you choose a different unique restore root, use the matching literal path everywhere and do not rely on glob or env vars.

Важно:

- `restore_snapshot` нельзя направлять на `/srv/medical-bot/data`;
- drill-директория должна быть новой и пустой;
- live overwrite запрещён;
- внешний архив `snapshot.tar` сначала safely unpacked в новый incoming dir, потом проверяется, потом только используется в isolated restore.

### 5. Подготовить runtime env

Скопируй примеры локально на VM и задай права `600`.

```bash
cd /opt/telegram_client_manager
cp deploy/zb.env.example deploy/zb.env
cp deploy/oci-backup.env.example deploy/oci-backup.env
chmod 600 deploy/zb.env deploy/oci-backup.env
```

Дальше заполни реальные значения вручную и не выводи их в лог:

- `deploy/zb.env`: токен ZB и `MISTRAL_API_KEY`, при необходимости `MISTRAL_MODEL`;
- `deploy/oci-backup.env`: `OCI_REGION`, `OCI_NAMESPACE`, `OCI_BUCKET`, `OCI_BACKUP_WORK_ROOT`.

Не добавляй в репозиторий ни один из этих файлов.
Это именно placeholder/config файлы, а не секретные артефакты.

### 6. Провести compose preflight на VM

Эти команды должны выполняться уже на Ubuntu VM, не на Windows.

Гейт перед первым `docker compose up -d bot-zb`:

- локальный `python -m bot.run` остановлен;
- если на этом же `BOT_TOKEN_ZB` уже работает другой polling-процесс, он тоже остановлен;
- только после этого поднимай compose.

```bash
cd /opt/telegram_client_manager
docker compose -f /opt/telegram_client_manager/compose.yaml config --quiet
docker compose -f /opt/telegram_client_manager/compose.yaml build --pull bot-zb
docker compose -f /opt/telegram_client_manager/compose.yaml up -d bot-zb
docker compose -f /opt/telegram_client_manager/compose.yaml ps
docker compose -f /opt/telegram_client_manager/compose.yaml logs --tail=200 bot-zb
```

Что сверять в логах:

- нет `Conflict: terminated by other getUpdates request`;
- нет `database is locked`;
- нет `Permission denied`;
- нет ошибок чтения job store;
- bot показывает, что загрузил reminders jobs из persistent store.

### 7. Установить systemd units

Ставь units только после того, как Docker preflight отработал нормально.

```bash
sudo install -m 644 /opt/telegram_client_manager/deploy/systemd/bot-zb.service /etc/systemd/system/bot-zb.service
sudo install -m 644 /opt/telegram_client_manager/deploy/systemd/bot-zb-backup.service /etc/systemd/system/bot-zb-backup.service
sudo install -m 644 /opt/telegram_client_manager/deploy/systemd/bot-zb-backup.timer /etc/systemd/system/bot-zb-backup.timer
sudo systemd-analyze verify /etc/systemd/system/bot-zb.service /etc/systemd/system/bot-zb-backup.service /etc/systemd/system/bot-zb-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now bot-zb.service
```

Назначение units:

- `bot-zb.service` поднимает один контейнер `bot-zb`;
- `bot-zb-backup.service` делает verified OCI backup и потом возвращает bot;
- `bot-zb-backup.timer` запускает backup ежедневно в 03:30.

### 8. Проверить OCI-gates перед первым upload

До первого успешного upload должны проходить такие проверки:

```bash
oci --version
oci os ns get --auth instance_principal
```

Bucket должен быть private. Имя bucket, namespace и compartment не хранятся в Git.

Policy и dynamic group на стороне OCI создаются отдельно и только после явного внешнего approval. Runtime instance principal должен иметь только объектную загрузку в нужный bucket/prefix, без list/delete/overwrite прав. В этом runbook не фиксируется policy beyond the minimum needed for object upload. Никаких URL, OCID или секретов в репозиторий не заносить.

### 9. Выполнить synthetic first upload

Первый upload должен быть осознанной проверкой, а не фоновым автоматом.

```bash
sudo systemctl start bot-zb-backup.service
sudo systemctl status bot-zb-backup.service --no-pager
sudo journalctl -u bot-zb-backup.service -n 200 --no-pager
```

Если upload прошёл, проверь появление объекта в OCI Console или отдельной admin-identity, а не через runtime instance principal. Для runtime principal не нужен `oci os object list`.
Только после этого включай таймер:

```bash
sudo systemctl enable --now bot-zb-backup.timer
```

### 10. Что делать с временной рабочей папкой backup

Поведение уже зафиксировано в коде:

- при успехе local work dir удаляется автоматически;
- при ошибке local work dir сохраняется для ручного разбора;
- не удаляй failed work dir автоматически до ревью;
- после успешного ручного разбора удаление делай уже явно.

### 11. Ручная остановка, обновление и rollback

Остановить bot:

```bash
sudo systemctl stop bot-zb.service
```

Перезапуск после обновления:

```bash
cd /opt/telegram_client_manager
git pull --ff-only
docker compose -f /opt/telegram_client_manager/compose.yaml build --pull bot-zb
sudo systemctl start bot-zb.service
docker compose -f /opt/telegram_client_manager/compose.yaml ps
docker compose -f /opt/telegram_client_manager/compose.yaml logs --tail=200 bot-zb
```

Rollback-правило:

- перед включением локального `bot-zb` cloud-container должен быть остановлен;
- перед включением cloud-container локальный `bot-zb` должен быть остановлен;
- один token = один активный polling-процесс.

Если надо вернуться к локальному хосту, сначала забери свежие cloud DB и только потом поднимай local bot. Сначала подтверждай, что другой polling-экземпляр остановлен.

## Очистка временных путей

После успешного initial cutover или завершённого restore drill, и только после ручной проверки точного пути, можно удалить эти временные каталоги:

- `/tmp/telegram-migration`
- `/tmp/telegram-staging`
- `/tmp/telegram-restore`

Перед удалением каждый путь нужно ещё раз сверить буквально по символам. Failed OCI backup work dirs не трогай автоматически: их разбирают отдельно и сохраняют до завершения ручного расследования.

Когда точный literal path подтверждён, очистка выглядит так:

```bash
rm -rf /tmp/telegram-migration
rm -rf /tmp/telegram-staging
rm -rf /tmp/telegram-restore
```

Если выбрал другой unique restore root, используй именно его literal path в команде и не подставляй шаблоны, glob или env vars.

## Чек-лист перед cutover

- VM на Ubuntu 24.04 ARM64.
- Docker и Compose v2 установлены.
- Python 3.11+ установлен.
- OCI CLI установлен и работает с instance principal.
- `deploy/zb.env` и `deploy/oci-backup.env` существуют, имеют права `600` и не попали в Git.
- `/srv/medical-bot/data/zb.db` и `/srv/medical-bot/data/reminders.db` существуют и проходят integrity check.
- Runtime assets присутствуют в `/srv/medical-bot/data`.
- `docker compose config --quiet` проходит.
- `docker compose build --pull bot-zb` проходит.
- `docker compose up -d bot-zb` проходит.
- `systemd-analyze verify` проходит.
- `bot-zb-backup.service` делает first upload успешно.

## Что не зафиксировано здесь специально

- никакой policy retention для удаления remote objects не выбирается в этом документе;
- никакой бот второй клиники не запускается;
- никакой webhook, домен, Nginx или TLS не добавляются;
- никакой ordinary copy живых SQLite/WAL файлов не используется;
- никакой production overwrite live data не выполняется без отдельного ручного решения.
