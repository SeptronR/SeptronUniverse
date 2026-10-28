# Runbook — Storage quota & cleanup

* Uploads live in S3 (versioned bucket, previous versions kept 90 days) or the local `uploads` volume.
* Phase 36 / 37 retention purges report files and archives; `jobs.cleanup` removes expired job artefacts.
* Disk alert (> 80 %): check `docker system df`, prune old images (`docker image prune -a --filter until=168h`), confirm the pgBackRest spool is draining to S3.
