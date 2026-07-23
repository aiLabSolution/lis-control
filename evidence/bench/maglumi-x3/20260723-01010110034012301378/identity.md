# Identity — MAGLUMI X3 bench capture 2026-07-23 (client lab, LIS-266)

- Model: SNIBE MAGLUMI X3 (service card + side label; `nameplate.jpg` is authoritative)
- Serial: 01010110034012301378 (side label; service card writes it 010101100340/2301378 — photo is the record)
- Site: Corazon Locsin Montelibano Memorial Regional Hospital, Burgos-Lacson St., Bacolod City
- Installed: 2020-09-18 by LabSolution Technologies Inc. (property sticker)
- Preventive maintenance: done 2026-02-13; next service due 2026-08-13
- Working temperature rating: 18–32 °C
- Operation PC: Lenovo, Windows 10 (10.0.18363.418); chassis link NIC 172.16.50.11/16, bench NIC 192.168.1.100/24 (`operation-pc-ipconfig.jpg`)
- Capture host: bench laptop 192.168.1.50:2003 (WSL2 listener behind netsh portproxy; true-peer record in `windows-netstat-connect.txt`)
- Online config as-found: Online Setting=None, saved target 10.1.52.78:2003, ASTM, checksum OFF (`online-screen-before.jpg` = rollback record)
- Online config for capture: TCP/IP, 192.168.1.50:2003, all else unchanged; LIS indicator green (`lis-indicator-green.jpg`)

## Session constraint (2026-07-23 evening)
Lab is OUT of reagents and consumables — no live chassis run possible tonight.
Stored past results exist on the operation PC (dummy/training data per medtech, names are
not real patients). Plan: manual re-upload of a stored result → capture is labeled
MANUAL RESEND, not auto-upload-at-completion. The chassis-attached auto-upload AC of
LIS-266 remains OPEN pending a reagent-stocked run.
