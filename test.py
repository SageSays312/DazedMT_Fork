from util.translation import validate_translation_content
ok, idx, reasons = validate_translation_content(
    ["The", "Pan", "Bash", "Sting", "Sorcerer Reinhart"],
    ["Зе", "Пан", "Баш", "Стинг", "Колдун Райнхарт"],
    langRegex=r"[\u3040-\u30ff\u4e00-\u9fff]",  # подставь реальный
)
print(ok, idx, reasons)