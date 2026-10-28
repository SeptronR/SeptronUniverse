# Runbook — Provider outage (payments, SMS, WhatsApp, e-mail, push)

* Detection: Phase 38 health checks mark `outage:<capability>:<provider>` when ≥ 50 % of ≥ 2 tenants fail; the status page shows the component degraded.
* Mitigation: switch tenants to a configured fallback connection (`/admin/integrations`), extend payment due dates if gateways are down (fees settings), pause campaigns.
* Credits: record affected message volumes for the provider dispute.
* Recovery: health checks clear the outage key; announce resolution.
