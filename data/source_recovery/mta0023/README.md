# Frozen MTA-0023 primary-source responses

Scope: only ocds-b3wdp1-MD-1659961877383 and ocds-b3wdp1-MD-1665058207960.
19 HTTP requests total, including redirects and 404 probes; budget20. No further requests are made by the offline analysis script.

http_provenance.json records original URL, retrieval time, status, headers, body size and SHA-256. Files01.body through19.body preserve response body bytes, including error/redirect bodies. HTTP transfer framing is excluded. Nothing overwrites the existing raw packages.

- 02.body /08.body: latest EV release-package JSON; not historical chains.
- 09.body /10.body: distinct8-page PDF notices for August (initial candidate and amendment candidate).
- 11.body /12.body: identical4-page October PDF notices, two storage URLs.
- 13.body /14.body: current base record JSON; parsed content identical to the MTA-0022 local packages.
- 01,03–07: HTTP301 redirect bodies.
- 15–19: HTTP404 from constructed, undocumented routes for exact known amendment releaseIDs. These are route probes, not supplied historical URI evidence; failure does not prove absence of server-side history.

PDF bodies can be opened as PDF without conversion. Never resave/modify them: embedded signature fields and incremental revisions must remain intact. Signature metadata is not cryptographic validation or proof of public availability. Source timestamps in2022 are claims requiring independent publication provenance. SHA-256 establishes captured-file identity only.

Source/resource relationships, exact IDs, field limitations and inspection pages: reports/MTA-0023_SOURCE_RECOVERY_PILOT.md and results/tables/mta0023_release_versions.csv. Offline reproduction: .venv/bin/python scripts/54_source_recovery_pilot.py.
