# Requirements Verification Matrix — Maritime PNT Integrity Monitor v1.0

Generated 2026-10-19 by `pntv verify`. 8 of 8 requirements pass.

Evidence: 480 Monte Carlo runs (20 real vessel tracks off San Diego x 6 seeds x 4 scenarios), 59.97 h of nominal operation, 120 spoofing attacks at 0.5, 1.0, 2.0 m/s.

| ID | Requirement | Method | Threshold | Measured | Result |
|---|---|---|---|---|---|
| PNT-001 | **Nominal position accuracy.** With nominal GNSS, the 95th-percentile horizontal position error shall not exceed 5.0 m. | Test | <= 5.0 | 3.0168 | PASS |
| PNT-002 | **GNSS outage holdover.** During a 300 s GNSS outage, the 95th-percentile horizontal error shall not exceed 50 m using dead reckoning. | Test | <= 50.0 | 10.972 | PASS |
| PNT-003 | **Accuracy under jamming.** While GNSS noise is degraded to 25 m (1-sigma) by jamming, the 95th-percentile horizontal error shall not exceed 20 m. | Test | <= 20.0 | 6.8723 | PASS |
| PNT-004 | **Spoofing detection probability.** A GNSS drag-off spoof moving the reported position at 0.5 m/s or faster shall be detected in at least 95% of runs. | Test | >= 0.95 | 0.9833 | PASS |
| PNT-005 | **Spoofing time to alert.** The 95th-percentile time from spoof onset to integrity alarm shall not exceed 60 s. | Test | <= 60.0 | 23 | PASS |
| PNT-006 | **Containment under spoofing.** Throughout a spoofing attack, the 95th-percentile horizontal error shall not exceed 50 m. | Test | <= 50.0 | 11.4439 | PASS |
| PNT-007 | **False alarm rate.** With nominal GNSS, integrity alarms shall occur no more than once per 10 hours of operation. | Test | <= 1.0 | 0.3335 | PASS |
| PNT-008 | **Processing time.** One dead-reckoning prediction plus one GNSS update shall take no more than 1 ms on the reference machine. | Test | <= 1.0 | 0.0858 | PASS |
