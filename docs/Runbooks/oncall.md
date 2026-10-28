# Runbook — On-call handbook

* Rota: weekly primary + secondary; handover notes in the ops channel. Critical alerts page by SMS + e-mail (Alertmanager `oncall` route); warnings go to the channel.
* First 5 minutes: acknowledge, check `/super-admin/ops` overview and Grafana overview, decide incident vs noise.
* Escalate to the incident lead for anything customer-visible > 15 minutes.
* Runbooks in this folder; every alert annotation names the matching runbook.
