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

1. DEV releases must be GitHub prereleases.
2. DEV releases must use tags formatted as `DEV-x.x.x-dev.x`.
3. DEV updater logic must not depend on GitHub `/releases/latest`.
4. Source-mode DEV machines are treated as current and must read local `config/version.json` as the version source.
5. Packaged DEV clients must read `config/dev_version.json` through raw.githubusercontent.com.
6. DEV validation may read the tag-specific release API or raw `config/dev_version.json`, but it must not use GitHub latest badge behavior.
7. DEV updater logic must not read `version.json` from GitHub Release assets.

STABLE channel rules:

1. Stable releases must use tags formatted as `vX.X.X`.
2. Stable releases may be marked as GitHub latest.
3. Stable updater logic may use `/releases/latest/download/version.json`.
4. Stable update checks must not consume DEV prerelease manifests.

Release pipeline rules:

1. DEV pipeline creates prereleases and uploads `TongYangCustomsPlatform.exe`, `version.json`, and `SHA256.txt`.
2. DEV pipeline updates `config/dev_version.json` after every DEV build.
3. DEV pipeline verifies tag-specific assets and download URLs, not `/releases/latest`.
4. STABLE pipeline creates normal releases and verifies `/releases/latest`.
5. GitHub Release asset executable name is always `TongYangCustomsPlatform.exe`.
