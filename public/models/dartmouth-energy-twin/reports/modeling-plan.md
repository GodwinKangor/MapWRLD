# Dartmouth Energy Twin Modeling Plan

## Scene Snapshot

- Local blend: `public/models/dartmouth-energy-twin/dartmouth-energy-twin.blend`
- Building candidates: 730
- Road/path candidates: 1496
- Building bounds min: (-792.16, -831.41, -1.00)
- Building bounds max: (792.16, 831.41, 21.64)

## Recommended Modeling Order

1. Start with the largest central landmarks so the campus reads correctly from far away.
2. Add roof forms and height corrections before facade detail.
3. Work one region at a time using crop renders: northwest, northeast, southwest, southeast.
4. Keep roads/paths as context until building massing is stable.
5. Export web-ready GLB only after each region has clean naming, scale, and materials.

## Largest Building Candidates

- `Areas.182` [south_east]: 204.8 x 142.5 x 6.0, center=(349.9, -532.9)
- `Areas.178` [north_east]: 106.9 x 122.7 x 20.0, center=(290.6, 621.0)
- `Areas.002` [south_east]: 123.5 x 101.7 x 20.0, center=(394.4, -278.4)
- `Areas.029` [south_east]: 127.9 x 96.0 x 20.0, center=(294.3, -74.0)
- `Areas.136` [south_west]: 81.3 x 123.2 x 20.0, center=(-43.4, -197.8)
- `Areas.005` [south_east]: 83.2 x 86.3 x 20.0, center=(384.0, -47.5)
- `Areas.547` [south_east]: 73.3 x 89.0 x 20.0, center=(755.5, -266.8)
- `Areas.176` [north_east]: 90.6 x 69.4 x 20.0, center=(186.2, 560.6)
- `Areas.001` [south_east]: 103.5 x 57.9 x 20.0, center=(597.1, -264.6)
- `Areas.006` [south_east]: 43.7 x 130.9 x 20.0, center=(318.7, -224.1)
- `Areas.222` [north_west]: 77.1 x 73.6 x 20.0, center=(-84.3, 198.1)
- `Areas.057` [north_east]: 75.0 x 73.4 x 20.0, center=(44.5, 362.2)
- `Areas.003` [south_east]: 47.8 x 115.0 x 20.0, center=(219.4, -246.8)
- `Areas.271` [south_west]: 68.7 x 78.3 x 15.0, center=(-91.2, -154.1)
- `Areas` [south_east]: 52.6 x 95.7 x 20.0, center=(689.9, -260.4)
- `Areas.521` [south_west]: 68.0 x 69.6 x 20.0, center=(-191.1, -300.4)
- `Areas.497` [north_west]: 61.1 x 76.7 x 20.0, center=(-560.4, 19.0)
- `Areas.590` [south_east]: 70.8 x 66.0 x 20.0, center=(20.2, -182.5)
- `Areas.058` [north_east]: 67.0 x 60.0 x 20.0, center=(128.7, 320.0)
- `Areas.146` [south_east]: 53.5 x 68.4 x 20.0, center=(152.0, -218.2)
- `Areas.507` [south_east]: 59.6 x 58.2 x 3.0, center=(303.0, -464.7)
- `Areas.156` [north_west]: 70.1 x 48.3 x 20.0, center=(-575.8, 127.5)
- `Areas.137` [south_east]: 60.9 x 55.4 x 9.0, center=(61.6, -230.0)
- `Areas.060` [north_east]: 55.7 x 60.2 x 20.0, center=(110.6, 207.1)
- `Areas.503` [south_east]: 45.9 x 70.9 x 20.0, center=(568.0, -579.8)
- `Areas.407` [south_east]: 62.2 x 51.9 x 20.0, center=(408.0, -370.0)
- `Areas.120` [north_west]: 64.6 x 48.3 x 20.0, center=(-519.0, 451.3)
- `Areas.054` [north_east]: 60.4 x 51.2 x 20.0, center=(8.3, 316.7)
- `Areas.162` [north_west]: 56.3 x 54.4 x 20.0, center=(-592.1, 178.0)
- `Areas.008` [north_west]: 48.4 x 61.0 x 20.0, center=(-25.2, 427.4)
- `Areas.052` [north_east]: 41.7 x 69.2 x 20.0, center=(104.4, 267.4)
- `Areas.223` [north_west]: 68.0 x 41.6 x 20.0, center=(-80.0, 254.8)
- `Areas.096` [south_west]: 88.4 x 30.9 x 20.0, center=(-265.3, -37.1)
- `Areas.284` [north_west]: 56.7 x 46.6 x 20.0, center=(-638.1, 32.4)
- `Areas.226` [south_east]: 31.6 x 83.0 x 20.0, center=(336.1, -208.2)

## Tallest Building Candidates

- `Areas.713` [north_east]: height=21.6, footprint=23
- `Areas` [south_east]: height=20.0, footprint=5031
- `Areas.001` [south_east]: height=20.0, footprint=5991
- `Areas.002` [south_east]: height=20.0, footprint=12557
- `Areas.003` [south_east]: height=20.0, footprint=5496
- `Areas.004` [south_east]: height=20.0, footprint=2411
- `Areas.005` [south_east]: height=20.0, footprint=7178
- `Areas.006` [south_east]: height=20.0, footprint=5725
- `Areas.007` [north_east]: height=20.0, footprint=1595
- `Areas.008` [north_west]: height=20.0, footprint=2955
- `Areas.009` [north_west]: height=20.0, footprint=486
- `Areas.010` [north_east]: height=20.0, footprint=582
- `Areas.011` [south_east]: height=20.0, footprint=247
- `Areas.012` [south_east]: height=20.0, footprint=108
- `Areas.013` [south_east]: height=20.0, footprint=117
- `Areas.014` [south_east]: height=20.0, footprint=241
- `Areas.015` [south_east]: height=20.0, footprint=163
- `Areas.016` [south_east]: height=20.0, footprint=74
- `Areas.017` [north_east]: height=20.0, footprint=148
- `Areas.018` [north_east]: height=20.0, footprint=193

## Regional Work Queues


### North West

- `Areas.222`: footprint=5669, height=20.0, center=(-84.3, 198.1)
- `Areas.497`: footprint=4691, height=20.0, center=(-560.4, 19.0)
- `Areas.156`: footprint=3380, height=20.0, center=(-575.8, 127.5)
- `Areas.120`: footprint=3124, height=20.0, center=(-519.0, 451.3)
- `Areas.162`: footprint=3065, height=20.0, center=(-592.1, 178.0)
- `Areas.008`: footprint=2955, height=20.0, center=(-25.2, 427.4)
- `Areas.223`: footprint=2829, height=20.0, center=(-80.0, 254.8)
- `Areas.284`: footprint=2641, height=20.0, center=(-638.1, 32.4)
- `Areas.113`: footprint=2456, height=20.0, center=(-350.4, 234.4)
- `Areas.157`: footprint=2306, height=20.0, center=(-582.4, 91.5)
- `Areas.158`: footprint=2197, height=20.0, center=(-709.4, 136.6)
- `Areas.063`: footprint=2183, height=20.0, center=(-100.0, 338.1)
- `Areas.283`: footprint=2013, height=20.0, center=(-684.3, 23.5)
- `Areas.735`: footprint=1851, height=20.0, center=(-577.2, 181.9)
- `Areas.161`: footprint=1829, height=20.0, center=(-644.3, 173.9)

### North East

- `Areas.178`: footprint=13111, height=20.0, center=(290.6, 621.0)
- `Areas.176`: footprint=6288, height=20.0, center=(186.2, 560.6)
- `Areas.057`: footprint=5510, height=20.0, center=(44.5, 362.2)
- `Areas.058`: footprint=4019, height=20.0, center=(128.7, 320.0)
- `Areas.060`: footprint=3355, height=20.0, center=(110.6, 207.1)
- `Areas.054`: footprint=3090, height=20.0, center=(8.3, 316.7)
- `Areas.052`: footprint=2885, height=20.0, center=(104.4, 267.4)
- `Areas.177`: footprint=2493, height=20.0, center=(224.8, 612.2)
- `Areas.179`: footprint=2430, height=20.0, center=(358.3, 667.0)
- `Areas.059`: footprint=2379, height=20.0, center=(68.6, 252.9)
- `Areas.180`: footprint=2176, height=20.0, center=(107.7, 607.2)
- `Areas.169`: footprint=2090, height=20.0, center=(54.5, 595.0)
- `Areas.026`: footprint=1886, height=20.0, center=(343.8, 118.9)
- `Areas.007`: footprint=1595, height=20.0, center=(31.9, 119.5)
- `Areas.173`: footprint=1434, height=20.0, center=(71.9, 437.4)

### South West

- `Areas.136`: footprint=10020, height=20.0, center=(-43.4, -197.8)
- `Areas.271`: footprint=5378, height=15.0, center=(-91.2, -154.1)
- `Areas.521`: footprint=4731, height=20.0, center=(-191.1, -300.4)
- `Areas.096`: footprint=2734, height=20.0, center=(-265.3, -37.1)
- `Areas.088`: footprint=2521, height=20.0, center=(-18.5, -344.2)
- `Areas.218`: footprint=2290, height=20.0, center=(-53.8, -314.2)
- `Areas.094`: footprint=2049, height=6.0, center=(-188.7, -70.9)
- `Areas.498`: footprint=1690, height=20.0, center=(-129.8, -400.9)
- `Areas.193`: footprint=1569, height=20.0, center=(-190.8, -350.7)
- `Areas.261`: footprint=1493, height=20.0, center=(-290.4, -497.4)
- `Areas.449`: footprint=1478, height=20.0, center=(-525.0, -398.9)
- `Areas.244`: footprint=1434, height=20.0, center=(-235.8, -441.6)
- `Areas.245`: footprint=1395, height=9.0, center=(-132.8, -453.6)
- `Areas.252`: footprint=1351, height=20.0, center=(-113.0, -206.8)
- `Areas.186`: footprint=1301, height=20.0, center=(-82.1, -354.3)

### South East

- `Areas.182`: footprint=29186, height=6.0, center=(349.9, -532.9)
- `Areas.002`: footprint=12557, height=20.0, center=(394.4, -278.4)
- `Areas.029`: footprint=12273, height=20.0, center=(294.3, -74.0)
- `Areas.005`: footprint=7178, height=20.0, center=(384.0, -47.5)
- `Areas.547`: footprint=6522, height=20.0, center=(755.5, -266.8)
- `Areas.001`: footprint=5991, height=20.0, center=(597.1, -264.6)
- `Areas.006`: footprint=5725, height=20.0, center=(318.7, -224.1)
- `Areas.003`: footprint=5496, height=20.0, center=(219.4, -246.8)
- `Areas`: footprint=5031, height=20.0, center=(689.9, -260.4)
- `Areas.590`: footprint=4674, height=20.0, center=(20.2, -182.5)
- `Areas.146`: footprint=3655, height=20.0, center=(152.0, -218.2)
- `Areas.507`: footprint=3467, height=3.0, center=(303.0, -464.7)
- `Areas.137`: footprint=3371, height=9.0, center=(61.6, -230.0)
- `Areas.503`: footprint=3255, height=20.0, center=(568.0, -579.8)
- `Areas.407`: footprint=3228, height=20.0, center=(408.0, -370.0)
