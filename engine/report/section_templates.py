from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SectionTemplate:
    key: str
    nav_label: str
    title: str
    fields: tuple[str, ...]
    explanation_hint: str


SECTION_TEMPLATES = (
    SectionTemplate(
        key="document_completeness",
        nav_label="文件完整度",
        title="文件完整度",
        fields=(),
        explanation_hint="先確認必要文件是否齊全；缺少關鍵文件時，後續欄位只能列為無法確認。",
    ),
    SectionTemplate(
        key="declaration",
        nav_label="報單核對",
        title="報單核對",
        fields=("item_no", "description", "quantity", "package_count", "unit", "amount", "currency"),
        explanation_hint="報單核對需確認品名、數量、件數、金額與幣別是否能被正式文件支持。",
    ),
    SectionTemplate(
        key="clearance",
        nav_label="清表核對",
        title="清表核對",
        fields=("description", "quantity", "unit", "hs_code"),
        explanation_hint="清表需與報單、INV、PL 及核退標準一致；品名與數量不應任意改寫。",
    ),
    SectionTemplate(
        key="tax_amount",
        nav_label="稅額驗算",
        title="稅額驗算",
        fields=("amount", "currency", "hs_code"),
        explanation_hint="稅額需回到完稅價格、稅則、稅率與幣別換算檢查。",
    ),
    SectionTemplate(
        key="vessel_voyage",
        nav_label="船名航次",
        title="船名航次",
        fields=("vessel_voyage", "vessel", "voyage"),
        explanation_hint="船名航次應以 SO、B/L 與報單交叉核對，常見差異為空白、斜線與 OCR 合併。",
    ),
    SectionTemplate(
        key="port",
        nav_label="港口",
        title="港口",
        fields=("port", "pol", "pod", "origin"),
        explanation_hint="港口需確認裝港、卸港、目的國與文件邏輯一致。",
    ),
    SectionTemplate(
        key="closing_date",
        nav_label="結關日",
        title="結關日",
        fields=("etd", "eta"),
        explanation_hint="結關日需依 S/O、Booking 與船期資料確認，避免用錯航次或船期。",
    ),
    SectionTemplate(
        key="package_count",
        nav_label="件數",
        title="件數",
        fields=("package_count", "unit"),
        explanation_hint="件數需確認數字與包裝單位是否一致；BLE / BALES、PCS / PCE 可視為同義單位。",
    ),
    SectionTemplate(
        key="container",
        nav_label="櫃號",
        title="櫃號封條",
        fields=("container_no", "seal_no"),
        explanation_hint="櫃號封條需以 B/L、裝箱明細與報單交叉核對，缺文件時不能視為已完成。",
    ),
    SectionTemplate(
        key="weight",
        nav_label="重量",
        title="重量",
        fields=("gross_weight", "net_weight"),
        explanation_hint="重量需確認 KG / KGS 與 MT / MTS 換算是否一致，並避免毛重誤填為淨重。",
    ),
    SectionTemplate(
        key="amount",
        nav_label="金額",
        title="金額",
        fields=("amount", "currency"),
        explanation_hint="金額需與 INV、報單幣別及貿易條件一致，必要時需回推單價與總價。",
    ),
    SectionTemplate(
        key="unit_price",
        nav_label="單價",
        title="單價",
        fields=("amount", "quantity", "net_weight"),
        explanation_hint="單價應由數量或重量回推總價，確認 INV 與報單金額邏輯一致。",
    ),
    SectionTemplate(
        key="cif",
        nav_label="CIF",
        title="CIF / FOB",
        fields=("amount", "currency"),
        explanation_hint="CIF 應由 FOB、FRT、INS 組成；若缺任一來源，需人工確認申報基礎。",
    ),
    SectionTemplate(
        key="exchange_rate",
        nav_label="匯率",
        title="匯率",
        fields=("amount", "currency"),
        explanation_hint="匯率需確認幣別、報單匯率與台幣離岸價格是否合理。",
    ),
    SectionTemplate(
        key="hs_code",
        nav_label="稅則",
        title="稅則",
        fields=("hs_code", "description"),
        explanation_hint="稅則需與品名、材質、用途及輸入規定交叉判斷，不應只比對代碼字串。",
    ),
    SectionTemplate(
        key="statistics",
        nav_label="統計方式",
        title="統計方式",
        fields=("quantity", "unit", "hs_code"),
        explanation_hint="統計方式需依稅則與申報單位判斷，數量單位不可與包裝單位混用。",
    ),
    SectionTemplate(
        key="import_regulation",
        nav_label="輸入規定",
        title="輸入規定",
        fields=("hs_code", "description"),
        explanation_hint="輸入規定需依稅則、品名與用途判斷是否涉及簽審、BSMI、MP1 或其他限制。",
    ),
    SectionTemplate(
        key="risk",
        nav_label="風險項目",
        title="風險項目",
        fields=(),
        explanation_hint="彙整缺件、不一致、高風險與需要人工判斷的欄位。",
    ),
    SectionTemplate(
        key="final_review",
        nav_label="最終確認",
        title="最終確認",
        fields=(),
        explanation_hint="確認是否可申報、是否需補件，以及是否有高風險欄位需主管或人工覆核。",
    ),
)


SECTION_BY_KEY = {template.key: template for template in SECTION_TEMPLATES}
SECTION_BY_NAV_LABEL = {template.nav_label: template for template in SECTION_TEMPLATES}
