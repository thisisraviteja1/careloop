# Evaluation: personal baseline vs fixed timers

> This is a simulation that tests the logic, not real-world accuracy. Histories are synthetic; incidents are days with no activity at all.

Regenerate with `python scripts/evaluate.py`. Same data for every method; CareLoop is judged with the production `compute_baseline` and `evaluate` functions, using only days before the day being judged.

**Parameters:** seed 2026; 90 days per setting; first 21 days are history only; 8 incident days (no activity) per setting; naturally late mornings on 5% of days (+45–100 min); weekends 25–30 min later; CareLoop margin 45 min.

- **False alarms:** alerts on days the person did appear (out of the normal judged days).
- **Missed:** incident days with no alert.
- **Delay:** minutes from the person's usual first appearance to the alert, on incident days (median / worst).

## Early riser (about 7:00 AM)

| Morning variability | Method | False alarms | Missed | Delay (median / worst) |
|---|---|---|---|---|
| low (±8 min) | CareLoop baseline | 3 of 61 days (4.9%) | 0 of 8 | 54 min / 84 min |
| low (±8 min) | Fixed timer 8:00 AM | 3 of 61 days (4.9%) | 0 of 8 | 60 min / 60 min |
| low (±8 min) | Fixed timer 9:00 AM | 0 of 61 days (0.0%) | 0 of 8 | 120 min / 120 min |
| low (±8 min) | Fixed timer 10:00 AM | 0 of 61 days (0.0%) | 0 of 8 | 180 min / 180 min |
| medium (±15 min) | CareLoop baseline | 2 of 61 days (3.3%) | 0 of 8 | 82 min / 126 min |
| medium (±15 min) | Fixed timer 8:00 AM | 3 of 61 days (4.9%) | 0 of 8 | 60 min / 60 min |
| medium (±15 min) | Fixed timer 9:00 AM | 0 of 61 days (0.0%) | 0 of 8 | 120 min / 120 min |
| medium (±15 min) | Fixed timer 10:00 AM | 0 of 61 days (0.0%) | 0 of 8 | 180 min / 180 min |
| high (±25 min) | CareLoop baseline | 3 of 61 days (4.9%) | 0 of 8 | 105 min / 119 min |
| high (±25 min) | Fixed timer 8:00 AM | 4 of 61 days (6.6%) | 0 of 8 | 60 min / 60 min |
| high (±25 min) | Fixed timer 9:00 AM | 0 of 61 days (0.0%) | 0 of 8 | 120 min / 120 min |
| high (±25 min) | Fixed timer 10:00 AM | 0 of 61 days (0.0%) | 0 of 8 | 180 min / 180 min |

## Late riser (about 8:40 AM)

| Morning variability | Method | False alarms | Missed | Delay (median / worst) |
|---|---|---|---|---|
| low (±8 min) | CareLoop baseline | 4 of 61 days (6.6%) | 0 of 8 | 78 min / 116 min |
| low (±8 min) | Fixed timer 8:00 AM | 61 of 61 days (100.0%) | 0 of 8 | -40 min / -40 min |
| low (±8 min) | Fixed timer 9:00 AM | 20 of 61 days (32.8%) | 0 of 8 | 20 min / 20 min |
| low (±8 min) | Fixed timer 10:00 AM | 2 of 61 days (3.3%) | 0 of 8 | 80 min / 80 min |
| medium (±15 min) | CareLoop baseline | 1 of 61 days (1.6%) | 0 of 8 | 59 min / 71 min |
| medium (±15 min) | Fixed timer 8:00 AM | 61 of 61 days (100.0%) | 0 of 8 | -40 min / -40 min |
| medium (±15 min) | Fixed timer 9:00 AM | 20 of 61 days (32.8%) | 0 of 8 | 20 min / 20 min |
| medium (±15 min) | Fixed timer 10:00 AM | 0 of 61 days (0.0%) | 0 of 8 | 80 min / 80 min |
| high (±25 min) | CareLoop baseline | 3 of 61 days (4.9%) | 0 of 8 | 84 min / 105 min |
| high (±25 min) | Fixed timer 8:00 AM | 59 of 61 days (96.7%) | 0 of 8 | -40 min / -40 min |
| high (±25 min) | Fixed timer 9:00 AM | 22 of 61 days (36.1%) | 0 of 8 | 20 min / 20 min |
| high (±25 min) | Fixed timer 10:00 AM | 5 of 61 days (8.2%) | 0 of 8 | 80 min / 80 min |

## Reading the results

Worst case for each method across all six settings (both people, all three variability levels), with no per-person tuning:

| Method | Most false alarms in any setting | Slowest median delay | Earliest median alert |
|---|---|---|---|
| CareLoop baseline | 4 of 61 days (7%) | 105 min | 54 min |
| Fixed timer 8:00 AM | 61 of 61 days (100%) | 60 min | -40 min |
| Fixed timer 9:00 AM | 22 of 61 days (36%) | 120 min | 20 min |
| Fixed timer 10:00 AM | 5 of 61 days (8%) | 180 min | 80 min |

A negative delay means the timer fires before the person usually gets up, so it alerts on almost every normal day.

What this shows, and what it doesn't:

- A fixed timer can match CareLoop for one person when it happens to be set right for them (for the early riser, an 8:00 AM timer has a similar number of false alarms and a shorter delay than CareLoop). The same timer is wrong for someone else: no single fixed time works for both people here.
- CareLoop sets its threshold from each person's own history, so it needs no tuning. The cost is the 45-minute margin after the usual window, which makes its median delay longer than a well-chosen timer's.
- CareLoop's remaining false alarms come from the naturally late mornings built into the simulation. That is why the camera check and the elder-first check-in come before any family member is alerted.
- No method missed an incident, because an incident here is a whole day with no activity. Partial-activity incidents are not modelled.

![False alarms and detection delay by method](evaluation.png)
