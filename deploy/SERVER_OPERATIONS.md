# ZB VPS: памятка владельца сервера

Дата актуальности: 2026-08-26. Это эксплуатационная памятка: как безопасно
управлять текущим ZB-ботом в Oracle Cloud. Если документ расходится с реальным
состоянием Oracle Console или выводом команд, первичны Console и команды.

## Главное за 30 секунд

- Рабочая ВМ называется **`zb-bot-vps`**. Её нормальный статус — `Running`.
- Бот — systemd-служба **`bot-zb.service`**, не запуск из Windows/NSSM и не
  ручной `python -m bot.run`.
- Бэкап запускает **`bot-zb-backup.timer`** ежедневно в **03:30 UTC**
  (**08:30 Asia/Tashkent**).
- Данные на ВМ: `/srv/medical-bot/data`; код: `/opt/telegram_client_manager`.
- Бэкапы лежат в **private** OCI Object Storage bucket. Он не должен быть
  public и не должен иметь публичных ссылок (Pre-Authenticated Requests).
- Для одного Telegram-токена возможен только один polling-процесс. Локальный
  бот на ноутбуке и облачный бот не запускаются одновременно.

## Нормальное состояние

| Что | Норма | Где проверить |
|---|---|---|
| ВМ | `zb-bot-vps` — `Running` | OCI Console → Compute → Instances |
| Бот | `active`, `enabled` | SSH: `systemctl is-active bot-zb.service` |
| Бэкап-таймер | `active`, `enabled`, есть следующий запуск | SSH: `systemctl list-timers bot-zb-backup.timer` |
| Системный диск | один подключённый boot volume | Страница ВМ → Storage |
| Бэкапы | появляются объекты с актуальной датой | Object Storage → Buckets → backup bucket → Objects |

Статус `Running` у ВМ не доказывает, что бот отвечает. Для бота всегда
проверяют службу и журналы.

## Куда заходить в Oracle Console

Открой [Oracle Cloud Console](https://cloud.oracle.com/) и проверь, что выбран
домашний регион **Middle East (Dubai) / `me-dubai-1`**.

### ВМ

`☰ Navigation menu` → **Compute** → **Instances** → `zb-bot-vps`.

| Вкладка | Зачем нужна | Что делать |
|---|---|---|
| **Details** | проверить имя, форму и `Running` | в основном только просмотр |
| **Networking** | IP, VNIC, правила доступа | проверить SSH; не открывать лишние порты |
| **Storage** | увидеть системный диск | сверить, что boot volume `Attached` |
| **Management** | диагностика/восстановление доступа | использовать только при проблеме SSH |

### Бэкапы

`☰` → **Storage** → **Object Storage & Archive Storage** → **Buckets** →
backup bucket → **Objects**.

После успешного backup там появляется новый объект. Проверяй дату и размер, но
не скачивай и не открывай медицинские данные без необходимости.

На вкладке **Management / Policies** bucket-а видны lifecycle rules. Не создавай
правило `Delete` для всех объектов «на пробу»: удалённые lifecycle policy
объекты Oracle не восстанавливает.

### Лимиты и возможные платные ресурсы

`☰` → **Governance & Administration** → **Limits, Quotas and Usage**.

Проверяй Compute, Block Volume и Object Storage. Это место для просмотра
лимитов, а не для их изменения без отдельного расчёта.

## Что не нажимать

| Действие | Риск | Что делать вместо |
|---|---|---|
| **Terminate instance** у `zb-bot-vps` | удаляет рабочую ВМ; диалог может предлагать удалить boot volume | для краткого простоя остановить только `bot-zb.service` |
| **Terminate/Delete** boot volume живой ВМ | ВМ не загрузится, данные могут быть потеряны | проверять `Storage` именно внутри страницы живой ВМ |
| **Stop/Restart instance** для обновления бота | останавливает весь сервер и бот | после обычного обновления: `sudo systemctl restart bot-zb.service` |
| Менять shape, OCPU, RAM или размер boot volume | можно выйти за Always Free и получить счёт | оставить текущую конфигурацию до отдельного решения |
| Делать bucket public или создавать PAR-ссылку | копии содержат базу и медицинские документы | bucket всегда private |
| Открывать порты в Security List/NSG «для удобства» | увеличивает риск взлома | polling-боту не нужен входящий HTTP/HTTPS; SSH — только TCP/22 и по возможности от вашего IP |
| Удалять backup objects/lifecycle rules | можно лишиться восстановления | сначала доказать, что есть более новые проверенные копии |
| Вставлять ключ, `.env`, токен, OCID или backup в чат/Git | это даёт доступ к серверу или данным | секреты остаются локально и не печатаются в логи |

## Регулярная проверка

Делай 1–2 раза в неделю, после деплоя и после любого письма Oracle:

1. В Console: `zb-bot-vps` имеет статус `Running`.
2. Проверь бота обычным безопасным сообщением, не создавая тестовые медицинские
   записи в реальных данных.
3. После 08:30 по Ташкенту проверь появление свежего объекта в Object Storage.
4. Раз в месяц выполни SSH-проверку:

```bash
sudo systemctl is-active bot-zb.service
sudo systemctl is-enabled bot-zb.service
sudo systemctl is-active bot-zb-backup.timer
sudo systemctl is-enabled bot-zb-backup.timer
systemctl list-timers bot-zb-backup.timer --no-pager
df -h / /srv/medical-bot/data
sudo journalctl -u bot-zb.service -n 100 --no-pager
sudo journalctl -u bot-zb-backup.service -n 100 --no-pager
```

Для первых четырёх строк ожидаются `active` и `enabled`. При `failed` или
`inactive` ничего не удаляй: сначала прочитай логи.

## Как войти по SSH

На Windows нужны OpenSSH Client, ваш приватный SSH-ключ, публичный IP из
`zb-bot-vps` → **Networking** и Linux-пользователь `ubuntu`.

```powershell
ssh -i "C:\ПУТЬ\К\ВАШЕМУ_КЛЮЧУ" ubuntu@<PUBLIC_IP>
```

SSH использует ключ, а не пароль Ubuntu. Passphrase, если она есть, защищает
файл ключа на вашем ПК; её нельзя отправлять кому-либо. При первом подключении
сверяй fingerprint: неожиданная смена — повод остановиться и проверить IP/ВМ.

Если Windows не находит `ssh` или `ssh-add`, добавь системную возможность
**OpenSSH Client** через `Settings` → `System` → `Optional features` → `View
features`. Не создавай новый ключ, пока не проверены путь к старому ключу и
обычная команда `ssh`.

## Управление ботом по SSH

Все команды ниже выполняются после входа как `ubuntu`.

### Состояние и логи

```bash
sudo systemctl status bot-zb.service --no-pager
sudo journalctl -u bot-zb.service -n 200 --no-pager
```

Логи вживую:

```bash
sudo journalctl -u bot-zb.service -f
```

`Ctrl+C` прекращает только просмотр, а не бот.

### Безопасный перезапуск

```bash
sudo systemctl restart bot-zb.service
sudo systemctl is-active bot-zb.service
sudo journalctl -u bot-zb.service -n 100 --no-pager
```

Это уместно при зависании или после подготовленного обновления. Во время
перезапуска бот кратко недоступен. Не перезапускай несколько раз подряд: сначала
прочитай логи первого запуска.

### Остановить/запустить вручную

```bash
sudo systemctl stop bot-zb.service
sudo systemctl start bot-zb.service
sudo systemctl is-active bot-zb.service
```

Это затрагивает реальных пользователей. Не запускай `python -m bot.run`,
ручной `docker compose up` или локальный NSSM-бот, пока на VPS активна служба:
иначе два poller-а одного токена будут конфликтовать в Telegram.

## Обновление кода

Код правится и тестируется только на ПК, затем попадает на ВМ как проверенный
конкретный Git-коммит. Это не синхронизация папок: базы, медицинские документы,
`.env` и ключи **не** передаются из Git и остаются на сервере в защищённых
runtime-путях.

### Обычный порядок после включения GitHub-deploy

1. На ПК внеси изменение и прогони подходящие тесты.
2. Проверь состав изменений и отправь проверенный коммит в GitHub.
3. Открой GitHub → **Actions** → workflow **Deploy ZB**.
4. В выпадающем списке выбери ветку **`codex/vps-migration`** с нужным коммитом.
5. Нажми **Run workflow** и в поле подтверждения введи ровно `DEPLOY_ZB`.
6. Дождись зелёного завершения run. Затем проверь бота обычным безопасным
   сообщением и, после ближайшего запуска таймера, наличие свежего backup-object
   в Object Storage.

Workflow разворачивает именно выбранный SHA, берёт общий maintenance-lock с
backup-задачей, пересобирает контейнер и проверяет service. Если run красный,
не запускай его много раз подряд: открой его лог, проверь состояние службы и
сохрани причину ошибки.

### Текущий статус автоматики

Автоматический деплой **активирован и проверен 2026-08-26**. На ВМ работает
выделенный self-hosted GitHub runner `zb-production-runner`; он принимает только
задачи workflow **Deploy ZB**. Последний проверенный запуск доставил ревизию
`abbc108` и завершился зелёным статусом. Перед следующим обновлением не нужно
входить на ВМ и не нужно вручную выполнять `git pull` или Docker-команды:
используй порядок выше через **Actions**.

Если в Actions нет кнопки **Run workflow**, сначала открой сам workflow
**Deploy ZB**, затем выбери нужную ветку. Подтверждающее слово `DEPLOY_ZB`
защищает от случайного ручного запуска. После зелёного run проверь службу и
одним обычным сообщением — Telegram, но не редактируй код прямо на сервере.

Не пытайся заменить его обычным `git pull`, `docker compose build` или ручным
редактированием `/opt/telegram_client_manager`: это обходит проверку exact
commit, deploy/backup-lock и rollback-логику. Не используй `git reset --hard`,
`git clean -fd`, force-pull или ручное удаление файлов на ВМ: они могут
уничтожить локальную конфигурацию или данные.

### Что допустимо делать по SSH

После уже выполненного деплоя по SSH разрешены только проверка и один осознанный
перезапуск при понятной причине:

```bash
sudo systemctl status bot-zb.service --no-pager
sudo journalctl -u bot-zb.service -n 200 --no-pager
sudo systemctl restart bot-zb.service
sudo systemctl is-active bot-zb.service
```

Python-код прямо на сервере не редактируется: следующая доставка его затрёт.
Сырые логи и копии баз не отправляй в чат или публичный Git — в них могут быть
медицинские данные.

## Резервные копии и восстановление

### Как устроен backup

Таймер запускает `bot-zb-backup.service`. Она:

1. кратко останавливает контейнер, чтобы получить согласованную SQLite-копию;
2. создаёт и проверяет snapshot;
3. загружает его в private OCI Object Storage;
4. запускает бот обратно даже при ошибке backup-задачи.

Поэтому во время backup возможен краткий простой. При ошибке приоритет — логи
и проверка, что бот вернулся в `active`; не нужно отключать таймер или удалять
рабочие файлы «чтобы заработало».

### Проверить таймер и сделать одну тестовую копию

Проверка без создания копии:

```bash
systemctl list-timers bot-zb-backup.timer --no-pager
sudo systemctl status bot-zb-backup.timer --no-pager
```

Внеплановый тест создаёт новый объект в Object Storage и может кратко остановить
бот:

```bash
sudo systemctl start bot-zb-backup.service
sudo systemctl status bot-zb-backup.service --no-pager
sudo journalctl -u bot-zb-backup.service -n 200 --no-pager
sudo systemctl is-active bot-zb.service
```

После этого в Console проверь новый объект. Успешный upload важен, но не заменяет
периодический isolated restore drill.

Не делай следующее:

- не копируй живые SQLite `*.db`, `-wal`, `-shm` обычным `cp`;
- не восстанавливай архив поверх `/srv/medical-bot/data`;
- не удаляй старые backup-objects, пока нет более новых проверенных копий;
- не давай runtime ВМ права `list`, `read`, `delete` или `overwrite`, если ей
  достаточно создавать новые backup-объекты;
- не задавай lifecycle `Delete` без выбранного срока хранения.

Полный технический restore runbook — [`README.md`](README.md), разделы
«Провести локальный verify и isolated restore drill» и «Ручная остановка,
обновление и rollback». Восстановление всегда начинается с изолированной staging
папки и проверки checksum, не с перезаписи live data.

## Как добавить доступ другому человеку

Не передавай свой private key. Каждый администратор делает **свою** SSH-пару, а
на сервер добавляется только его public key (`ssh-ed25519 ...`, одна строка).

1. Получи public key нового администратора.
2. Войди на ВМ своим действующим ключом.
3. Добавь public key отдельной строкой в `/home/ubuntu/.ssh/authorized_keys`,
   не меняя существующие строки.
4. Проверь права: `.ssh` — `700`, `authorized_keys` — `600`.
5. Пусть человек войдёт в отдельном окне. Доступ добавлен только после этого
   теста.
6. При отзыве удаляется ровно его строка, после проверки владельца ключа.

Для OCI Console добавляй пользователя через IAM с минимальными правами и MFA.
Не делай его tenancy administrator, если ему нужен только просмотр ВМ/бэкапов.

## Добавление ресурсов

Пока не добавляй вторую ВМ, второй boot volume, Load Balancer, БД или rescue-ВМ
«на всякий случай». Это может занять Always Free лимит, стать платным и усложнить
восстановление. Сначала измерь проблему:

```bash
free -h
nproc
df -h /
docker stats --no-stream
```

Для A1 Always Free общий предел сейчас — **2 OCPU и 12 GB RAM на tenancy**;
суммарно boot/block volumes — **200 GB в домашнем регионе**. Перед изменением
сверяй Limits, label **Always Free Eligible** и экран ожидаемой стоимости.

## Почему Oracle может отключить, удалить или тарифицировать

### Idle reclamation — главный риск Always Free

Oracle может reclaim idle Always Free VM. По текущему официальному правилу ВМ
считается idle, если в течение 7 дней одновременно выполняются:

- 95-й перцентиль CPU utilization ниже 20%;
- network utilization ниже 20%;
- для A1 также memory utilization ниже 20%.

Не нужно искусственно нагружать ВМ майнером, CPU-loop или фальшивым трафиком:
это ненадёжно и может нарушать правила. Реальная защита — обычная рабочая
нагрузка, мониторинг, off-site бэкапы и готовый restore plan.

### Trial и превышение лимитов

После trial Always Free ресурсы продолжают работать, но платные ресурсы,
созданные на trial credits, могут быть reclaimed без перехода на paid account.
Расходы также появляются, если выбрать не Always-Free shape/image, создать
ресурс вне home region, превысить квоты или добавить платный сервис.

Перед созданием любого ресурса проверь регион `me-dubai-1`, label **Always Free
Eligible**, общий лимит OCPU/RAM и monthly cost на review-экране.

### Другие реальные риски

- случайно нажать `Terminate` / удалить boot volume / очистить bucket;
- утечка private key, `.env`, Telegram token или отсутствие MFA;
- открытый миру SSH и устаревшая ОС;
- ошибка Docker, Telegram API, сети, диска или нового обновления.

Во всех этих случаях сначала проверяй `systemctl` и `journalctl`, а не создавай
новую ВМ и не удаляй старую.

## Аварийный порядок

| Симптом | Первые действия | Не делать |
|---|---|---|
| ВМ `Running`, бот не отвечает | SSH → service status → логи → один restart при понятной причине | не запускать второй local poller и не создавать ВМ |
| SSH не пускает | проверить IP, `ubuntu`, ключ, `authorized_keys`, TCP/22 | не публиковать private key и не угадывать пароли |
| ВМ не `Running` | сохранить статус/время, проверить backup bucket, планировать восстановление | не нажимать `Terminate`, не удалять boot volume |
| Backup failed | прочитать логи, убедиться, что бот снова `active`, проверить Object Storage | не отключать защиту/не удалять failed workdir до разбора |
| Появился счёт | записать имя, регион, shape, expected cost, проверить Limits | не создавать новые ресурсы «для исправления» |

## Официальные ссылки

- [Oracle Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) — лимиты A1, block volume и reclaim idle VM.
- [Oracle Cloud Free Tier](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm) — поведение после trial.
- [Object Storage Lifecycle Management](https://docs.oracle.com/en-us/iaas/Content/Object/Tasks/usinglifecyclepolicies.htm) — lifecycle rules и необратимость удаления.
- [Object Storage Security](https://docs.oracle.com/en-us/iaas/Content/Security/Reference/objectstorage_security.htm) — private buckets, retention и IAM.

## Последняя проверка, которая ещё нужна

Таймер backup включён. Чтобы зафиксировать цепочку после восстановления как
полностью проверенную, нужно увидеть **одну новую успешную копию** одновременно
в journal `bot-zb-backup.service` и в Object Storage. Это финальная проверка
backup-цепочки, а не новая настройка ВМ.
