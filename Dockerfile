FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY deploy/__init__.py deploy/runtime_assets.py deploy/container_entrypoint.py ./deploy/
COPY data/history_of_illness/templates/docx_gen_prompt.txt /opt/runtime-seed/history_of_illness/templates/docx_gen_prompt.txt
COPY data/history_of_illness/templates/zub_mudsrosti_med_card_filled.md /opt/runtime-seed/history_of_illness/templates/zub_mudsrosti_med_card_filled.md
COPY data/history_of_illness/templates/zub_mudsrosti_med_card_unfilled.md /opt/runtime-seed/history_of_illness/templates/zub_mudsrosti_med_card_unfilled.md
COPY data/history_of_illness/medical_card_filled.pdf /opt/runtime-seed/history_of_illness/medical_card_filled.pdf
COPY data/history_of_illness/medical_card_wisdom_tooth.docx /opt/runtime-seed/history_of_illness/medical_card_wisdom_tooth.docx
COPY data/location/location.png /opt/runtime-seed/location/location.png
COPY data/location/location_mm.png /opt/runtime-seed/location/location_mm.png
COPY data/price_list/price_mm.jpg /opt/runtime-seed/price_list/price_mm.jpg
COPY data/price_list/rus_1pg.png /opt/runtime-seed/price_list/rus_1pg.png
COPY data/price_list/rus_2pg.png /opt/runtime-seed/price_list/rus_2pg.png
COPY data/price_list/schedule_mm.jpg /opt/runtime-seed/price_list/schedule_mm.jpg
COPY data/price_list/uzb_1pg.png /opt/runtime-seed/price_list/uzb_1pg.png
COPY data/price_list/uzb_2pg.png /opt/runtime-seed/price_list/uzb_2pg.png

RUN groupadd --gid 10001 bot \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin bot \
    && chown -R 10001:10001 /app /opt/runtime-seed

USER 10001:10001

ENTRYPOINT ["python", "-m", "deploy.container_entrypoint"]
