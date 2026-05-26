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
        "document_identity",
        "文件完整度與單號",
        "文件完整度與單號",
        ("declaration_no", "invoice_no", "bl_no", "booking_no", "shipping_order_no", "container_no", "seal_no"),
        "先確認 INV、PL、SO、B/L、報單、清表、核退標準是否齊全，並核對報單號碼、INV NO、BL NO、Booking NO、櫃號與封條是否能互相支持。",
    ),
    SectionTemplate("vessel_voyage", "船名航次", "船名航次", ("vessel_voyage", "vessel", "voyage"), "船名航次應以 SO、B/L 與報單交叉核對，重點是同一船名與同一航次，不是單純字串完全相同。"),
    SectionTemplate("port", "港口", "港口", ("port", "pol", "pod", "origin"), "港口需確認裝港、卸港、目的港與文件邏輯一致。"),
    SectionTemplate("closing_date", "結關日", "結關日", ("closing_date", "etd", "eta"), "結關日需依 S/O、Booking 與船期資料確認，避免用錯航次或船期。"),
    SectionTemplate("package_count", "件數", "件數", ("package_count", "quantity", "unit"), "件數需確認數字與包裝單位是否一致；BLE、BALE、BALES 可視為同一包裝語意，櫃數不可當件數。"),
    SectionTemplate("weight", "重量", "重量", ("gross_weight", "net_weight"), "重量需確認 KG、KGS、MTS 的換算是否一致，並避免毛重誤填為淨重。"),
    SectionTemplate("amount", "金額", "金額", ("amount", "currency"), "金額需與 INV、報單幣別及貿易條件一致，必要時需回推單價與總價。"),
    SectionTemplate("unit_price", "單價", "單價", ("amount", "quantity", "net_weight"), "單價應由數量或重量回推總價，確認 INV 與報單金額邏輯一致。"),
    SectionTemplate("freight_insurance", "運費保費", "運費保費", ("freight", "insurance", "cif", "fob"), "CIF 應由 FOB、運費、保費組成；缺任一來源時需人工確認申報基礎。"),
    SectionTemplate("exchange_rate", "匯率", "匯率", ("exchange_rate", "currency", "amount", "cif"), "匯率需確認幣別、報單匯率與台幣完稅價格是否合理。"),
    SectionTemplate("hs_code", "稅則", "稅則", ("hs_code", "description"), "稅則需與品名、材質、用途及輸入規定交叉判斷，不應只比對代碼字串。"),
    SectionTemplate("statistics", "統計方式", "統計方式", ("statistical_method", "quantity", "unit", "hs_code"), "統計方式需依稅則與申報單位判斷，數量單位不可與包裝單位混用。"),
    SectionTemplate("parties_incoterm", "買賣方與 Incoterm", "買賣方與 Incoterm", ("customer", "supplier", "incoterm"), "買賣方、供應商與貿易條件會影響價格基礎、運保費認列與申報責任。"),
    SectionTemplate("risk", "風險提醒", "風險提醒", (), "彙整缺件、不一致、高風險與需要人工判斷的欄位。"),
    SectionTemplate("final_review", "最後結論", "最後結論", (), "確認是否可申報、是否需補件，以及是否有高風險欄位需主管或人工覆核。"),
)


SECTION_BY_KEY = {template.key: template for template in SECTION_TEMPLATES}
SECTION_BY_NAV_LABEL = {template.nav_label: template for template in SECTION_TEMPLATES}
