# Demo video script (under 3:00)

**Rules to follow** (from the hackathon rules): under 3 minutes, public on YouTube or Vimeo, in English. **It must show CareLoop working through the Ring Developer Playground (a simulator) or a real Ring device.** No copyrighted music, no third-party logos you don't have permission for, and no real faces or names. Lead with the best 60 seconds.

**Before recording**
- Generate a fresh Ring token less than 20 minutes before recording, and put it in `.env`.
- `make demo`, then click **Seed 28 days of history** once.
- Telegram open on your phone, with screen recording ready. Notifications on, Do Not Disturb off.
- Browser at 100% zoom, other tabs closed, and the dashboard full screen.
- Record each clip separately and record a backup take of each one. Edit them together at the end.

---

## 0:00–0:15 · Hook (voice over the dashboard)
> "Lakshmi is 78 and lives alone. Her son Suresh lives in another city. A fixed 'no activity by 9 AM' alarm either cries wolf on her slow mornings or waits hours on a bad one. CareLoop learns *her* routine from her Ring doorbell instead."

*Screen:* the dashboard in its normal state, then zoom in on the Morning routine chart.

## 0:15–0:30 · It's real Ring (simulator requirement)
> "CareLoop talks to the Ring API. Here it is connected through the Ring Developer Playground."

*Screen:* the Ring Developer Playground with the token generated (blur the token), then Terminal running `make probe` with HTTP 200 responses, then the dashboard's **Ring API connected** indicator.

## 0:30–1:20 · The moment: missed morning
Click **Run missed morning**.
> "This is her own routine: on [today's weekday]s she's usually at the door between [window start] and [window end]. The alert threshold is that window plus 45 minutes, not a fixed timer."

*(Read the weekday, window and threshold off the "Morning routine" chart on the day you record; they change with the weekday.)*

*Screen:* the chart, pausing one second on the dashed threshold line.
> "[Threshold time] and no one has been seen. Before worrying anyone, CareLoop takes one snapshot to describe with Amazon Bedrock. In this recording Bedrock isn't connected, so CareLoop falls back to its fixed, safe wording: it never stalls without the AI."

*Screen:* the status card turns to Escalating, with the camera line.
> "First, it asks Lakshmi herself."

*Phone:* the Telegram check-in with the **I'm OK** button.
> "No reply, so Suresh gets a calm message explaining exactly why."

*Phone:* the caregiver alert. Read the first sentence aloud.
> "Still nothing, so Meena next door is asked to knock."

## 1:20–1:45 · No false alarm
Click **Run late but normal**.
> "On a slow morning she appears at 7:40: later than usual, but within her margin. Nothing fires."

*Screen:* the evaluation chart (`docs/evaluation.png`).
> "On the same simulated data, an 8 AM timer alerted on every single day for a late riser. CareLoop stayed under 7% false alarms for both people, with no tuning."

## 1:45–2:10 · Trust and privacy
> "Statistics decide; AI only describes and phrases. Every model output is checked, and if anything looks wrong, a fixed template is sent instead."

*Screen:* the **Privacy and audit** panel.
> "Snapshots are taken only when something looks unusual, and never stored. Every access is logged right here."

## 2:10–2:35 · Accessibility, and the camera going down
*Phone or browser:* the big-button page.
> "Not everyone uses apps. The check-in link opens one big button."

Click **Run camera offline**.
> "And if the doorbell goes offline, CareLoop says monitoring is degraded instead of raising a false alarm."

## 2:35–2:55 · Close
> "CareLoop: caretaking and accessibility on Ring, with Amazon Bedrock, open source, and honest about its limits. This demo uses simulated history and a sample image; the code is public on GitHub."

*Screen:* the README on GitHub.

---

**Honest disclosures to keep on screen:** the dashboard banner already says "Demo controls · simulated data · fixture image". Keep it visible in every dashboard clip.
