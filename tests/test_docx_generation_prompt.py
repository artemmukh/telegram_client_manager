"""Contract tests for the medical-record generation system prompt."""

from bot.utils import prompt_builder


def test_prompt_maps_all_crown_aliases_to_the_universal_k_marker():
    prompt = prompt_builder.get_system_prompt()

    assert "«мк», «Мк» или «МК»" in prompt
    assert "«циркон», «фул» и «фулциркон» означают одно и то же" in prompt
    assert "«цлит» означает цельнолитую коронку" in prompt
    assert "Любая коронка, явно указанная для конкретного зуба" in prompt
    assert 'marker "K"' in prompt
    assert "«35, 45 постановка МК» и «35,45 постановка мк» трактуй одинаково" in prompt
    assert "исходную формулировку диагноза не изменяй и не добавляй в JSON новые ключи" in prompt
    assert 'поле "diagnosis"' not in prompt


def test_prompt_preserves_expanded_professional_medical_record_fields():
    prompt = prompt_builder.get_system_prompt()

    assert (
        "поля \"complaints\", \"diseases\", \"examination\", \"treatment\" "
        "ВСЕГДА должны быть заполнены развёрнутым профессиональным текстом"
    ) in prompt
    assert "Пустая строка в этих четырёх полях недопустима, если диагноз указан" in prompt
    assert "Не придумывай конкретные жалобы, глубину кариозной полости" not in prompt
    assert "используй нейтральную медицинскую формулировку" not in prompt


def test_prompt_maps_cervical_caries_and_reserves_x_for_tooth_conditions():
    prompt = prompt_builder.get_system_prompt()

    assert "«пришейка» означает пришеечный кариес V класса по Блэку" in prompt
    assert "Не используй \"X\" для коронок" in prompt


def test_prompt_defines_fdi_lists_and_inclusive_dental_arch_ranges():
    prompt = prompt_builder.get_system_prompt()

    assert "Тире обозначает включительный диапазон зубов" in prompt
    assert "«Мк 13-25» означает зубы 13, 14, 15, 16, 17, 18, 21, 22, 23, 24 и 25" in prompt
    assert "Точка разделяет несколько зубов" in prompt
    assert "Запятая разделяет несколько зубов" in prompt
    assert "Перенос строки разделяет несколько зубов" in prompt
