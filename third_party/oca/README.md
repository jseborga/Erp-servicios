# Módulos OCA incluidos

Copias sin modificar de módulos de la [Odoo Community Association](https://odoo-community.org),
rama `19.0`, fijadas a un commit. Se incluyen en el repositorio para que la imagen Docker
se construya sin descargar nada de GitHub y siempre con las mismas versiones probadas.

| Módulo | Repositorio OCA | Commit | Para qué |
|---|---|---|---|
| `account_financial_report` | account-financial-reporting | `0078bc03f234d1caa8b9f40324678ce9dbed2a72` | Balance de comprobación, libro mayor, antigüedad de saldos, libro diario (PDF/XLSX) |
| `account_tax_balance` | account-financial-reporting | `0078bc03f234d1caa8b9f40324678ce9dbed2a72` | Saldos por impuesto (IVA, IT, retenciones) |
| `mis_builder` | mis-builder | `7d519f31e1a553d7a5499571a9146f7e3ea49ea4` | Estados financieros configurables (resultados, balance, presupuestos) |
| `account_asset_management` | account-financial-tools | `ddcabb93373382148826f97bf9935424d03ddea5` | Activos fijos y depreciación |
| `account_fiscal_year` | account-financial-tools | `ddcabb93373382148826f97bf9935424d03ddea5` | Gestiones fiscales |
| `report_xlsx`, `report_xlsx_helper` | reporting-engine | `b9e8c6cdd2d106614eddaf81bd78f487ae35db45` | Dependencia: exportación a Excel |
| `date_range` | server-ux | `f2485eef1437b7fd57e3d44a61537420bbf1b281` | Dependencia: rangos de fechas |

Licencia: AGPL-3.0 (ver `LICENSE-AGPL-3.0`). Cada módulo conserva su `README.rst` con autores.

Instalados y probados juntos con `l10n_bo_spa` sobre Odoo 19.0 Community (commit
`2ff84495` de `odoo/odoo`) el 11-oct-2026.

## Actualizar

```bash
scripts/update_oca.sh   # edite primero los SHA en el script
```
