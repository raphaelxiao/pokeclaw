"""
TTS text preprocessor — converts raw LLM output into TTS-friendly Chinese text.

Rules extracted from ref.md / formatting.html and extended with
table/bullet handling. Only applied to chunks sent to TTS; the display
always shows the original unprocessed text.
"""

import re

# ── Emoji regex ──────────────────────────────────────────────────────────────
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F700-\U0001F77F"  # alchemical
    "\U0001F780-\U0001F7FF"  # geometric extended
    "\U0001F800-\U0001F8FF"  # supplemental arrows-C
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended-A
    "\u2600-\u26FF"          # misc symbols
    "\u2700-\u27BF"          # dingbats
    "]+",
    flags=re.UNICODE,
)

# ── Markdown table detection ────────────────────────────────────────────────
# Matches 2+ consecutive lines that start with |
_TABLE_RE = re.compile(r"(?:^[ \t]*\|.*$\n?){2,}", re.MULTILINE)

# ── Bullet list detection ───────────────────────────────────────────────────
# Matches consecutive lines starting with - or *
_BULLET_LINE_RE = re.compile(r"^[ \t]*[-*][ \t]+(.+)$", re.MULTILINE)

_CN_ORDINALS = [
    "第一", "第二", "第三", "第四", "第五",
    "第六", "第七", "第八", "第九", "第十",
    "第十一", "第十二", "第十三", "第十四", "第十五",
    "第十六", "第十七", "第十八", "第十九", "第二十",
]

# ── Number helpers ───────────────────────────────────────────────────────────
_CN_DIGITS = "零一二三四五六七八九"
_CN_UNIT = ["", "十", "百", "千"]
_CN_SECTION_UNIT = ["", "万", "亿", "万亿", "亿亿"]


def _section_to_chinese(section: int) -> str:
    """Convert a 4-digit section (0-9999) to Chinese."""
    result = ""
    unit_pos = 0
    zero = False
    while section > 0:
        v = section % 10
        if v == 0:
            if not zero:
                zero = True
                result = _CN_DIGITS[0] + result
        else:
            zero = False
            result = _CN_DIGITS[v] + _CN_UNIT[unit_pos] + result
        unit_pos += 1
        section //= 10
    return result.rstrip("零")


def num_to_chinese(num) -> str:
    """Convert a number (int or float, or string) to Chinese reading.

    Accepts a string to preserve trailing zeros (e.g. '129.80' -> 一百二十九点八零).

    Examples:
        12      -> 十二
        '129.80' -> 一百二十九点八零
        0.5     -> 零点五
    """
    # Keep the original string representation for decimal precision
    original_str = str(num)
    num_val = float(num)
    negative = num_val < 0
    num_val = abs(num_val)
    original_str = original_str.lstrip("-")

    int_part = int(num_val)
    # Use original string to preserve trailing zeros (e.g. '80' in '129.80')
    decimal_part = original_str.split(".")[1] if "." in original_str else ""
    # Remove decimal only if it's literally all zeros (integer passed as float)
    if decimal_part and all(c == "0" for c in decimal_part):
        decimal_part = ""

    if int_part == 0:
        chn = _CN_DIGITS[0]
    else:
        chn = ""
        unit_pos = 0
        need_zero = False
        remaining = int_part
        while remaining > 0:
            section = remaining % 10000
            if need_zero:
                chn = _CN_DIGITS[0] + chn
            s = _section_to_chinese(section)
            s += _CN_SECTION_UNIT[unit_pos] if section != 0 else ""
            chn = s + chn
            need_zero = 0 < section < 1000
            remaining //= 10000
            unit_pos += 1

    # Decimal
    if decimal_part:
        chn += "点"
        for ch in decimal_part:
            chn += _CN_DIGITS[int(ch)]

    # 一十 -> 十
    if chn.startswith("一十"):
        chn = chn[1:]

    if negative:
        chn = "负" + chn

    return chn


# ── Main preprocessor ───────────────────────────────────────────────────────

def _replace_tables(text: str) -> str:
    """Replace markdown tables with a spoken placeholder."""
    return _TABLE_RE.sub("此处我整理了表格，可以在屏幕阅读。", text)


def _replace_bullets(text: str) -> str:
    """Replace bullet lists with numbered Chinese reading.

    - apple       ->  第一，apple。第二，banana。第三，cherry。
    - banana
    - cherry
    """
    def _replace_block(match: re.Match) -> str:
        block = match.group(0)
        items = _BULLET_LINE_RE.findall(block)
        parts = []
        for i, item in enumerate(items):
            ordinal = _CN_ORDINALS[i] if i < len(_CN_ORDINALS) else f"第{num_to_chinese(i + 1)}"
            parts.append(f"{ordinal}，{item.strip()}")
        return "。".join(parts) + "。"

    # Match consecutive bullet lines as a block
    return re.sub(r"(?:^[ \t]*[-*][ \t]+.+$\n?)+", _replace_block, text, flags=re.MULTILINE)


def preprocess_for_tts(text: str) -> str:
    """Preprocess text for TTS — convert numbers, symbols, structures to spoken Chinese."""

    # ── 1. Structural content (tables, bullets) ──
    text = _replace_tables(text)
    text = _replace_bullets(text)

    # ── 2. Symbol replacements ──
    text = text.replace("～", "至")
    text = text.replace("——", "，")  # em-dash before single-char replacements
    text = text.replace("→", "至")
    text = re.sub(r"[>＞]", "大于", text)
    text = re.sub(r"[<＜]", "小于", text)
    text = re.sub(r"[=＝]", "等于", text)
    text = text.replace("≠", "不等于")
    text = re.sub(r"[+＋]", "加", text)

    # ── 3. Thousand separators (1,234 -> 1234) ──
    text = re.sub(r"(\d),(?=\d{3}(?:\D|$))", r"\1", text)

    # ── 4. Units ──
    text = re.sub(r"Wh/kg", "瓦时每千克", text)  # longer patterns first
    text = re.sub(r"GWh", "吉瓦时", text)
    text = re.sub(r"nm\b", "纳米", text)
    text = re.sub(r"(\d+)L\b", r"\1升", text)

    # ── 5. Remove emoji ──
    text = _EMOJI_RE.sub("", text)

    # ── 6. Negative percentages (-5.3% -> 负百分之五点三) ──
    def _neg_pct(m: re.Match) -> str:
        num_str = m.group(1)
        prefix = "负" if m.start() == 0 or text[m.start() - 1] != "负" else ""
        if "%" in m.group(0) or "％" in m.group(0):
            return prefix + "百分之" + num_to_chinese(num_str)
        else:
            return prefix + num_to_chinese(num_str)

    text = re.sub(r"[-－](\d+(?:\.\d+)?)[%％]?", _neg_pct, text)

    # ── 7. Positive percentages (12.5% -> 百分之十二点五) ──
    def _pct(m: re.Match) -> str:
        return "百分之" + num_to_chinese(m.group(1))

    text = re.sub(r"(\d+(?:\.\d+)?)[%％]", _pct, text)

    # ── 8. Numbers to Chinese (year-aware) ──
    def _num_replace(m: re.Match) -> str:
        matched = m.group(0)
        # Year or fiscal year: 2025年 / 2025财年 -> 二零二五年
        if re.match(r"^\d{4}(?:年|财年)$", matched):
            year_part = "".join(_CN_DIGITS[int(d)] for d in matched[:4])
            return year_part + matched[4:]
        else:
            return num_to_chinese(matched)  # pass string to preserve trailing zeros

    text = re.sub(r"\d{4}(?:年|财年)|\d+(?:\.\d+)?", _num_replace, text)

    return text


# ── Self-test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("价格129.80元", "价格一百二十九点八零元"),
        ("-5.3%", "负百分之五点三"),
        ("2025年", "二零二五年"),
        ("1,234万", "一千二百三十四万"),
        ("温度>30度", "温度大于三十度"),
        ("500L", "五百升"),
        ("3～5天", "三至五天"),
        ("增长12.5%", "增长百分之十二点五"),
        ("A>B", "A大于B"),
        ("100GWh", "一百吉瓦时"),
        (
            "| 名称 | 价格 |\n| --- | --- |\n| 苹果 | 5元 |",
            "此处我整理了表格，可以在屏幕阅读。",
        ),
        (
            "- 苹果\n- 香蕉\n- 橙子",
            "第一，苹果。第二，香蕉。第三，橙子。",
        ),
        (
            "- 第一点内容\n- 第二点内容",
            "第一，第一点内容。第二，第二点内容。",
        ),
    ]

    print("=" * 60)
    print("TTS Preprocess Self-Test")
    print("=" * 60)
    all_pass = True
    for input_text, expected in tests:
        result = preprocess_for_tts(input_text)
        status = "✓" if result == expected else "✗"
        if result != expected:
            all_pass = False
        print(f"\n{status} Input:    {input_text!r}")
        print(f"  Expected: {expected!r}")
        print(f"  Got:      {result!r}")

    print("\n" + "=" * 60)
    print("ALL PASSED" if all_pass else "SOME TESTS FAILED")
    print("=" * 60)

    # Sentence-splitting regex test
    print("\n--- Sentence split regex test ---")
    smart_re = re.compile(r"(?<!\d)\.(?!\d)\s*|[!?。！？:：;；]\s*|\n")
    test_cases = [
        ("价格129.80元。下一句", ["。"]),
        ("This is a sentence. Next one", ["."]),
        ("增长3.5%。好的", ["。"]),
    ]
    for text, expected_splits in test_cases:
        matches = [m.group() for m in smart_re.finditer(text)]
        print(f"  {text!r} => splits at: {matches}")
