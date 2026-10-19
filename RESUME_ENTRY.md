# Maritime PNT Integrity Monitor & Verification Toolkit
Tech: Python, NumPy, Kalman Filtering, YAML, pytest, Linux, GitHub Actions
- Built a GNSS/dead-reckoning extended Kalman filter for ships with chi-square integrity monitoring that detects GNSS spoofing, and rolls back and replays to keep spoofed fixes out of the estimate.
- Wrote 8 numbered system requirements and a verification toolkit that runs 480 Monte Carlo scenarios over 20 real AIS vessel tracks off San Diego and generates a requirements verification matrix.
- Verified all 8 requirements: 98.3% of spoofing attacks detected with 23 s 95th-percentile time to alert, 11 m error through a 300 s GNSS outage, and 0.33 false alarms per 10 hours.
