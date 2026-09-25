# Model scorecard

_Updated 25 Sep 2026_

## Summary

| GW | Players | Predicted avg | Actual avg | Bias | MAE | XI+C pred | XI+C actual |
|---|---|---|---|---|---|---|---|
| 4 | 219 | 3.07 | 3.30 | +0.23 | 2.53 | 61.8 | 93 |
| 5 | 214 | 3.04 | 3.55 | +0.50 | 2.49 | 61.6 | 65 |

## Calibration

Only 2 gameweek(s) scored. Too few to separate bias from variance -- do not tune anything yet. Five or six is the point at which this becomes readable.

## Minutes

| GW | Expected to start | Played under 60 | Did not play |
|---|---|---|---|
| 4 | 143 | 17 | 8 |
| 5 | 131 | 11 | 7 |

Early substitutions are expensive: 1 appearance point instead of 2, no clean sheet, and usually no defensive contribution. If this column stays high the minutes model is the problem, not the attacking projections.

## Biggest misses, GW5

| Player | Predicted | Actual | Error |
|---|---|---|---|
| B.Fernandes | 6.67 | 2 | -4.67 |
| João Pedro | 4.37 | 0 | -4.37 |
| Saka | 6.31 | 2 | -4.31 |
| M.Sangaré | 4.12 | 0 | -4.12 |
| Calafiori | 5.10 | 1 | -4.10 |

**By position, latest gameweek**

| Pos | n | Predicted avg | Actual avg |
|---|---|---|---|
| GKP | 20 | 3.22 | 4.20 |
| DEF | 79 | 2.88 | 3.56 |
| MID | 97 | 3.06 | 3.30 |
| FWD | 18 | 3.45 | 4.11 |