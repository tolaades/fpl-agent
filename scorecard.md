# Model scorecard

_Updated 21 Sep 2026_

## Summary

| GW | Players | Predicted avg | Actual avg | Bias | MAE | XI+C pred | XI+C actual |
|---|---|---|---|---|---|---|---|
| 4 | 219 | 3.07 | 3.30 | +0.23 | 2.53 | 61.8 | 93 |

## Calibration

Only 1 gameweek(s) scored. Too few to separate bias from variance -- do not tune anything yet. Five or six is the point at which this becomes readable.

## Minutes

| GW | Expected to start | Played under 60 | Did not play |
|---|---|---|---|
| 4 | 143 | 17 | 8 |

Early substitutions are expensive: 1 appearance point instead of 2, no clean sheet, and usually no defensive contribution. If this column stays high the minutes model is the problem, not the attacking projections.

## Biggest misses, GW4

| Player | Predicted | Actual | Error |
|---|---|---|---|
| Foden | 3.32 | -2 | -5.32 |
| Cherki | 6.11 | 1 | -5.11 |
| B.Fernandes | 7.07 | 2 | -5.07 |
| Reinildo | 2.54 | -2 | -4.54 |
| Gakpo | 5.47 | 1 | -4.47 |

**By position, latest gameweek**

| Pos | n | Predicted avg | Actual avg |
|---|---|---|---|
| GKP | 20 | 3.13 | 4.10 |
| DEF | 83 | 2.96 | 3.13 |
| MID | 95 | 3.13 | 3.02 |
| FWD | 21 | 3.10 | 4.43 |