# AI Customs ERP Contract

This contract defines boundaries for AI agents, audit logic, parser logic, and configurable business rules.

## Core Rule Boundary

Global rules and company-specific rules must never be mixed.

A rule is global only when it is valid for every import/export case regardless of company, customer, route, document source, carrier, forwarder, or manually assigned case condition.

Valid global rules include:

- 報單為核心。
- DS2 報單 vs INV / PKG / B/L / 到貨通知 / 清表。
- 品名逐字核對。
- 數量核對。
- 件數核對。
- 淨重 / 毛重核對。
- 金額 / 幣別核對。
- 櫃號 / 封條核對。
- 船名航次核對。
- 港口核對。
- 稅則 / 稅率 / 稅額核對。

The following are not global rules:

- 通盈越南 CFS CBM 運費。
- 20 呎 / 40 呎固定運費。
- INSURANCE RATE。
- 最低保費 400。

Those rules are company, customer, route, or case specific. They must only activate when configured activation conditions match the case.

## Required Rule Engine Contract

1. Audit engine must not hardcode company, customer, route, case, or document-specific business rules.
2. Audit engine may only call the rule engine and consume rule findings.
3. Rule engine must load configurable rules from `config/rules/`.
4. Every configurable rule must include `rule_id`, `scope`, `enabled`, `applies_when`, `priority`, `description`, `calculation`, `warning_level`, and `source`.
5. Rule engine must evaluate `applies_when` before running `calculation`.
6. If `applies_when` does not match the case context, the rule must not run and must not produce warnings.
7. Missing context is not a match unless the rule explicitly allows it.
8. Any rule that names a company, customer, forwarder, carrier, route, port, or document source is not global.

## Tong Ying Rule Contract

通盈規則是 company-specific。它們只能在 case context 明確表示通盈時啟用，例如 company、forwarder、document source 或 explicit case tag。

通盈越南 CFS CBM 運費只能在以下條件同時成立時啟用：

- `company == "通盈"`
- `shipment_type == "CFS"`
- `destination_country == "Vietnam"`

20 呎 / 40 呎固定運費、保險公式、保險費率、最低保費 400 也必須遵守相同原則，不得套用到所有案件。

## AI Agent Constraints

- Do not place company-specific calculations inside `v2.audit`, `v2.core.checking`, parser code, or UI code.
- Do not infer that a customer or route rule is global because it appears frequently in sample files.
- Do not activate a rule from keywords alone when scope conditions are missing.
- Do not render raw rule objects in UI; expose rule findings through view models.
- Prefer adding or editing JSON rules under `config/rules/` over changing Python code.

## Parser Boundary

Parsers classify and extract data. Parsers do not decide whether a business rule applies, except to provide evidence fields used by rule activation.

Rule activation remains the responsibility of the rule engine.

## Human-first Workflow Principle

AI Customs ERP is not a parser showcase. Its core product is a customs broker decision and audit workflow system.

Permanent workflow and UI rules:

1. Developer-console-first UI is prohibited.
2. Raw parser object rendering is prohibited.
3. Parser confidence must not be the primary information on the main screen.
4. Every workflow must prioritize missing documents, differences, high-risk fields, declaration readiness, and AI audit summaries.
5. Parser, OCR, and debug details are secondary layers only.
6. UI flows must simulate the real customs declaration review process.
7. Case workflow must be case-centered, not document-centered.
8. The system core is the AI Audit Summary Engine, not a parser viewer.
9. Every compare result must be convertible into a human-readable audit result.
10. System design priority is:

```text
Human workflow
> Audit clarity
> Workflow grouping
> Compare intelligence
> Parser debug
```

## Development Lifecycle Rules

DEV and STABLE release channels must remain separate.

DEV channel rules:

1. DEV releases must use the single fixed tag format `vX.X.X-dev`.
2. DEV releases are normal GitHub releases so `/releases/latest` can point to the current DEV release.
3. Only one active DEV release may exist at a time.
4. Every new DEV release must delete old DEV releases and old DEV tags.
5. DEV updater logic must read `/releases/latest/download/version.json`.
6. DEV `version.json` must point to `/releases/latest/download/TongYangCustomsPlatform.exe`.

STABLE channel rules:

1. Stable releases must use tags formatted as `vX.X.X`.
2. Stable releases may keep historical versions.
3. Stable updater logic may use `/releases/latest/download/version.json`.
4. Stable release creation must set its release as GitHub latest.

Release pipeline rules:

1. DEV pipeline creates or updates the single DEV release and uploads `TongYangCustomsPlatform.exe`, `version.json`, and `SHA256.txt`.
2. DEV pipeline cleans up old DEV releases and old DEV tags.
3. DEV and STABLE pipelines both verify assets, `version.json`, EXE download URL, and `/releases/latest`.
4. GitHub Release asset executable name is always `TongYangCustomsPlatform.exe`.
5. Release lifecycle behavior belongs in the Release Manager layer.
