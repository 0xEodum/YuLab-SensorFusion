# SF-08 weather, time and noise profile

`weather-response.v1` is a synthetic, deterministic capture profile. One
`EnvironmentSpec` and `CapturePlan` tick are checked before the worker builds a
scene. The RGB, IR, geometric reference and LiDAR passes use that frozen scene;
declared LiDAR beam time offsets do not animate it. `world`, `weather`, `rgb`,
`ir` and `lidar` seed channels are independent. Only the world seed affects
placement. Repeating a request on the same renderer/device reproduces the
observations; cross-device byte identity is not guaranteed.

The capture panel offers clear day, night, fog, rain, snow and hot-background
presets, a severity slider, solar hour, simulation tick and four separate noise
seeds. Night selects solar hour zero; a later solar-hour edit deliberately
changes illumination while retaining the selected weather fields. A time jump
uses `thermal_history=equilibrated`, recalculating surface equilibrium at the
selected condition. Evolve uses a hash-verified prior `thermal_state_json`
artifact and integrates forward to the new tick. Evolve cannot go backward or
run without a prior successful capture. This is an explicit UI choice; no
clock control silently advances or resets heat.

## Preset and response coefficients

All coefficients below scale linearly with severity `s` in `[0,1]`, except
the response noise terms. Baseline air temperature is 293.15 K. Fog sets
`fog_extinction_per_m=0.006s`; rain sets `rain_mm_per_h=45s`, wetness `s` and
wind X `3s` m/s; snow sets `snow_mm_per_h=24s`, air temperature
`293.15-20s` K and wind X `3s` m/s; hot background sets air temperature
`293.15+35s` K. Clear and night have no precipitation or fog.

Let `f`, `r`, `n` be fog extinction (m^-1), rain rate (mm/h) and snow rate
(mm/h). Band-specific extinction in m^-1 is:

| RGB | LWIR | LiDAR |
| --- | --- | --- |
| `f + 0.000035r + 0.00011n` | `0.22f + 0.000018r + 0.000045n` | `0.8f + 0.000045r + 0.00013n` |

These mappings are controlled test parameters, not measured meteorological
relationships. Sun elevation follows the selected solar hour. RGB uses fixed
exposure after scene lighting with gain `0.08 + 0.92 max(0,sun_y)`, so night
loses signal and SNR. Per-pixel RGB is blended with airlight using
`tau=exp(-beta_RGB d)`, then deterministic precipitation particles, a
depth-aware 3x3 precipitation blur, shot noise proportional to square root of
signal and 2 DN read noise are applied. The source is the renderer's existing
tone-mapped 8-bit RGB pass, so this is an observation degradation model rather
than a linear radiometric camera. Depth and instance-ID truth remain clean.

LWIR uses the independent IR camera's shader depth (optical distance
approximation): `L_sensor=exp(-beta_IR d)L_surface +
(1-exp(-beta_IR d))B_8..14(T_air)`. Seeded detector noise and saturation follow
that path response. The calibration records extinction, path radiance and
noise sigma. Hot background raises reflected and background radiance; there
is no global hot-weather penalty. Local contrast depends on the object and
background temperatures, so a hot engine can remain visible at crossover.

LiDAR tests the first opaque triangle before response. Pre-surface particle
distance follows an exponential distribution with rate
`0.000015r + 0.000035n` m^-1, sampled from the weather seed. A particle
becomes the single nearer return with class reference 0, and the ideal surface
truth remains separate. Otherwise surface intensity is attenuated by the
round-trip factor `exp(-2 beta_LiDAR d)`. A seeded detection draw and the
synthetic 0.015 intensity threshold can drop the surface. Range/intensity
receiver noise uses only the LiDAR seed. The beam table distinguishes
no return (0), surface (1), receiver dropout (2), particle (3), and
atmospheric dropout (4). A dropped front surface never reveals geometry behind
it. Particle returns have no object instance label.

## Statistical scope and cases outside the expected trend

SF-08 acceptance uses 30 paired seeds on a fixed two-tone RGB target and a
fixed 128-beam planar LiDAR fixture. The tests report normal-approximation
95% confidence intervals for paired contrast, SNR and return-count
differences. They are simulation repeatability checks, not uncertainty bounds
for real weather. Fog contrast loss can be negligible at very short range;
night SNR does not necessarily fall if exposure is deliberately increased;
hot backgrounds can increase contrast for objects cooler than the background;
and a high-intensity near LiDAR surface can keep returning under moderate
extinction. Scene geometry, calibration and ideal truth do not change in these
condition sweeps.
