# AI Customs ERP Architecture

## Rule Engine Layer

The platform uses a layered rule architecture:

1. Parser layer extracts structured facts from documents.
2. Workflow layer groups documents into cases.
3. Audit layer compares declaration values against source documents.
4. Rule engine layer evaluates configurable business rules.
5. UI layer displays case status, document workflow, compare results, and rule findings.

The audit layer must stay generic. Company, customer, route, case, and document-specific behavior belongs in the rule configuration layer and is activated by the rule engine.

## Rule Config Layer

Rule configuration files live under `config/rules/`:

- `global_rules.json`
- `company_rules.json`
- `customer_rules.json`
- `route_rules.json`
- `case_rules.json`
- `document_rules.json`

Each rule has the same core schema:

```json
{
  "rule_id": "string",
  "scope": "global | company | customer | route | case | document",
  "enabled": true,
  "applies_when": {},
  "priority": 100,
  "description": "string",
  "calculation": {},
  "warning_level": "info | warning | error | high_risk",
  "source": "string"
}
```

## Rule Activation Logic

The rule engine builds a case context from workflow and parser output. Example context fields:

- `company`
- `customer`
- `forwarder`
- `document_source`
- `case_tags`
- `shipment_type`
- `origin_country`
- `destination_country`
- `pol`
- `pod`
- `document_type`
- `declaration_type`
- `release_method`

Activation rules:

1. Disabled rules are ignored.
2. Rules are filtered by `scope`.
3. `applies_when` must match the case context.
4. Missing context fails the match unless the rule declares an explicit fallback.
5. Matching rules are sorted by `priority`.
6. Only matched rules run `calculation`.
7. Rule findings are returned to audit/UI as structured results.

## Rule Layer Separation

### Global Rules

Global rules apply to every case and are limited to universal customs checking principles: declaration-centered audit, field comparisons, document completeness, and tax/port/container/vessel consistency.

### Company Rules

Company rules apply only when a company, forwarder, document source, or case tag matches. 通盈 rules live in `company_rules.json` and must not appear in `global_rules.json`.

### Customer Rules

Customer rules apply only to a named customer. Example: 詩肯 may have multiple INV/PKG layouts, multiple suppliers, and customer-specific parser learning rules.

### Route Rules

Route rules apply only when country, port, or lane conditions match. Example: 越南 CFS handling must be route-specific or combined with company-specific conditions.

### Case Rules

Case rules apply only to one case or cases with explicit manual tags. Example: manually assigned C1 / C2 / C3M / C3X release methods.

### Document Rules

Document rules apply only to a document type or parser boundary. Example: Booking / S/O parser rules, B/L parser rules, 清表 parser rules, DS2 parser rules.

## Future Company Rule Process

To add a company rule:

1. Add a rule object to `config/rules/company_rules.json`.
2. Set `scope` to `company`.
3. Add a strict `applies_when` block with company and any required route, shipment, or case tags.
4. Define `calculation` as data, not Python hardcode.
5. Add `source` with the business owner, document, or ticket that authorized the rule.
6. Add tests proving the rule activates for matching cases and does not activate for non-matching cases.

Business specificity must move downward:

`global -> company/customer/route -> case -> document`

A rule can be promoted to global only when it is documented as universally true for all cases.

## Updater Architecture

Updater channels are separated by manifest source.

DEV updater:

1. Source-mode DEV machines do not update themselves and read local `config/version.json`.
2. Packaged DEV clients fetch `https://raw.githubusercontent.com/larry36163712-ux/tongyang-customs-platform/main/config/dev_version.json`.
3. `dev_version.json` contains `version`, `channel`, `download_url`, `sha256`, `build_time`, and optional `notes`.
4. DEV updater compares local `config/version.json` with raw `config/dev_version.json`.
5. When remote DEV is newer, it downloads `TongYangCustomsPlatform.exe`, verifies SHA256, schedules temp replacement, and restarts.
6. DEV updater must not use GitHub `/releases/latest` and must not read `version.json` from GitHub Release assets.

STABLE updater:

1. Stable clients fetch `/releases/latest/download/version.json`.
2. Stable releases are normal GitHub releases and may be marked latest.
3. Stable updater must not consume DEV prerelease manifests.

Release pipeline:

1. DEV build generates `dist/version.json` and syncs the same manifest to `config/dev_version.json`.
2. DEV build uploads release assets for direct EXE download, but update discovery uses raw `config/dev_version.json`.
3. STABLE build keeps using GitHub latest release manifest discovery.
