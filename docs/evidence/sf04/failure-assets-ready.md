# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: assets.spec.ts >> self-contained catalog, aircraft scale, streamed airfield and real geometry visibility fixtures
- Location: tests\browser\assets.spec.ts:12:1

# Error details

```
Error: expect(received).toHaveLength(expected)

Expected length: 0
Received length: 5
Received array:  ["aerodrome-0-clear", "aerodrome-0-wide", "aerodrome-0-partial", "aerodrome-0-hidden", "aerodrome-0-service"]
```

# Page snapshot

```yaml
- main [ref=e3]:
  - generic [ref=e4]:
    - link "← Preset editor" [ref=e5] [cursor=pointer]:
      - /url: ./
    - generic [ref=e6]: STRATA / CONNECTED WORLD
    - generic [ref=e7]: World explorer
  - generic [ref=e8]:
    - generic [ref=e9]:
      - paragraph [ref=e10]: ONE LANDSCAPE, CONTINUOUS GROUND
      - heading "A world beyond the edge." [level=1] [ref=e11]
      - paragraph [ref=e12]: 2,048 × 2,048 metres. Arches, tunnels and outcrops on connected terrain.
    - generic [ref=e13]:
      - strong [ref=e14]: "256"
      - generic [ref=e15]: chunks · 128 m each
  - region "Connected world preview" [ref=e16]:
    - generic [ref=e17]:
      - button "Natural landscape" [ref=e18] [cursor=pointer]
      - button "Open aerodrome" [pressed] [ref=e19] [cursor=pointer]
      - generic [ref=e20]: Airfield · 1,200 m runway · parked aircraft
    - generic [ref=e21]:
      - generic [ref=e22]:
        - text: World seed
        - spinbutton "Connected world seed" [ref=e23]: "0"
      - button "Generate world" [ref=e24] [cursor=pointer]
      - generic [ref=e25]:
        - text: Location
        - combobox "World location" [ref=e26]:
          - option "Aerodrome 1" [selected]
          - option "Alpine ridge 2"
          - option "Coastal bluff 3"
          - option "Canyon arch 4"
          - option "Alpine ridge 5"
          - option "Canyon arch 6"
          - option "Alpine ridge 7"
          - option "Canyon arch 8"
          - option "Alpine ridge 9"
          - option "Highland outcrops 10"
          - option "Canyon arch 11"
      - generic [ref=e27]:
        - text: View
        - combobox "World camera" [ref=e28]:
          - option "Landscape"
          - option "Landmark detail"
          - option "From above"
          - option "Ground level" [selected]
      - generic [ref=e29]:
        - text: Display detail
        - combobox "Display detail" [ref=e30]:
          - option "Landscape · 4 m" [selected]
          - option "Fine · 2 m"
      - generic [ref=e31]:
        - text: Navigation
        - combobox "Navigation" [ref=e32]:
          - option "Orbit / pan" [selected]
          - option "Free flight"
      - generic [ref=e33]:
        - checkbox "Chunk boundaries" [ref=e34]
        - text: Chunk boundaries
    - generic "Connected terrain. Drag to orbit, scroll to zoom." [ref=e35]:
      - generic "World navigation canvas" [ref=e36]
      - generic: Loading terrain…
    - status [ref=e37]:
      - generic [ref=e38]: Preparing connected terrain…
      - generic [ref=e39]: 76,002 faces · 13 trees · 49 rocks · 599 ms load
    - generic [ref=e40]:
      - generic [ref=e41]:
        - text: Rig pose name
        - textbox "Rig pose name" [ref=e42]: Rig 1
      - button "Save rig pose" [disabled] [ref=e43]
    - region "Model catalog" [ref=e44]:
      - generic [ref=e45]:
        - heading "Objects at world scale" [level=2] [ref=e46]
        - paragraph [ref=e47]: One unit is one metre. Original proportions, parked pose.
      - generic [ref=e48]:
        - article [ref=e49]:
          - heading "F-16" [level=3] [ref=e50]
          - paragraph [ref=e51]: 16.4 m long · 9.2 m wide · 5.0 m high
          - button "Inspect F-16" [disabled] [ref=e52]
        - article [ref=e53]:
          - heading "RQ-4 Global Hawk" [level=3] [ref=e54]
          - paragraph [ref=e55]: 15.1 m long · 39.9 m wide · 4.5 m high
          - button "Inspect RQ-4" [disabled] [ref=e56]
        - article [ref=e57]:
          - heading "8×8 ground vehicle" [level=3] [ref=e58]
          - paragraph [ref=e59]: 11.1 m long · 4.3 m wide · 5.9 m high
          - button "Inspect vehicle" [disabled] [ref=e60]
      - generic [ref=e61]:
        - generic [ref=e62]: Visibility fixtures
        - button "Unobstructed F-16" [disabled] [ref=e63]
        - button "Partial hangar occlusion" [disabled] [ref=e64]
        - button "Closed hangar" [disabled] [ref=e65]
  - generic [ref=e66]:
    - paragraph [ref=e67]: "Focus X -600 m, Z -700 m. Orbit: drag / scroll / right-drag. Flight: click canvas, W A S D to move, Q / E down / up, Shift for speed, drag to look."
    - paragraph [ref=e68]: Terrain loads as you move. Rig poses are saved per seed in this browser. Sensor capture arrives in a later stage.
```

# Test source

```ts
  1   | import { test, expect, type Page } from "@playwright/test";
  2   | import { mkdirSync, writeFileSync } from "node:fs";
  3   | 
  4   | async function ready(page: Page) {
  5   |   await page.waitForTimeout(150);
  6   |   await expect(page.locator(".world-canvas")).toHaveAttribute(
  7   |     "data-ready",
  8   |     "true",
  9   |     { timeout: 45000 },
  10  |   );
  11  | }
  12  | test("self-contained catalog, aircraft scale, streamed airfield and real geometry visibility fixtures", async ({
  13  |   page,
  14  | }) => {
  15  |   test.setTimeout(180000);
  16  |   const errors: string[] = [];
  17  |   page.on("pageerror", (e) => errors.push(e.message));
  18  |   await page.goto("/?view=world&site=aerodrome&qa=1");
  19  |   await expect(
  20  |     page.getByRole("button", { name: "Open aerodrome" }),
  21  |   ).toHaveAttribute("aria-pressed", "true");
  22  |   await expect
  23  |     .poll(
  24  |       () => page.evaluate(() => window.worldQA?.metrics().assetTemplates ?? 0),
  25  |       { timeout: 45000 },
  26  |     )
  27  |     .toBe(3);
  28  |   await ready(page);
  29  |   expect(
  30  |     (await page.evaluate(() => window.worldQA!.metrics())).assetIds,
  31  |   ).toHaveLength(5);
  32  |   mkdirSync("artifacts/sf04/browser", { recursive: true });
  33  |   await page
  34  |     .locator(".world-canvas")
  35  |     .screenshot({ path: "artifacts/sf04/browser/aerodrome.png" });
  36  |   await page.getByLabel("World camera").selectOption("opening");
  37  |   await ready(page);
  38  |   expect(
  39  |     await page.evaluate(() => window.worldQA!.camera.position.y),
  40  |   ).toBeCloseTo(28, 5);
  41  |   for (const [name, id] of [
  42  |     ["F-16", "f16"],
  43  |     ["RQ-4", "rq4"],
  44  |     ["vehicle", "ground-vehicle"],
  45  |   ]) {
  46  |     await page
  47  |       .getByRole("button", { name: `Inspect ${name}`, exact: true })
  48  |       .click();
  49  |     await ready(page);
  50  |     await page
  51  |       .locator(".world-canvas")
  52  |       .screenshot({ path: `artifacts/sf04/browser/${id}.png` });
  53  |   }
  54  |   const fractions: Record<string, unknown> = {};
  55  |   for (const [id, label] of [
  56  |     ["clear", "Unobstructed F-16"],
  57  |     ["partial", "Partial hangar occlusion"],
  58  |     ["hidden", "Closed hangar"],
  59  |   ]) {
  60  |     await page.getByRole("button", { name: label, exact: true }).click();
  61  |     await ready(page);
  62  |     await page
  63  |       .locator(".world-canvas")
  64  |       .screenshot({ path: `artifacts/sf04/browser/${id}.png` });
  65  |     const counts = await page.evaluate(
  66  |       (id) => window.worldQA!.inspectVisibility(id),
  67  |       id,
  68  |     );
  69  |     expect(counts.isolated).toBeGreaterThan(10);
  70  |     fractions[id] = counts;
  71  |     if (id === "clear") expect(counts.fraction).toBeGreaterThan(0.99);
  72  |     if (id === "partial") {
  73  |       expect(counts.fraction).toBeGreaterThan(0.05);
  74  |       expect(counts.fraction).toBeLessThan(0.95);
  75  |     }
  76  |     if (id === "hidden") expect(counts.visible).toBe(0);
  77  |   }
  78  |   const sensors = await page.evaluate(() =>
  79  |     window.worldQA!.prepareSensors([210, 28, 15], 100),
  80  |   );
  81  |   expect(sensors.ids).toContain("aerodrome-0-hidden");
  82  |   expect(sensors.structures).toContain("closed-door");
  83  |   const before = await page.evaluate(() => window.worldQA!.metrics());
  84  |   await page.evaluate(() => window.worldQA!.moveTo(-600, -700));
  85  |   await ready(page);
  86  |   expect(
  87  |     (await page.evaluate(() => window.worldQA!.metrics())).assetIds,
> 88  |   ).toHaveLength(0);
      |     ^ Error: expect(received).toHaveLength(expected)
  89  |   await page.getByRole("button", { name: "Inspect RQ-4", exact: true }).click();
  90  |   await ready(page);
  91  |   expect(
  92  |     (await page.evaluate(() => window.worldQA!.metrics())).assetIds.sort(),
  93  |   ).toEqual(before.assetIds.sort());
  94  |   const baseline = (await page.evaluate(() => window.worldQA!.metrics()))
  95  |     .renderer;
  96  |   for (let i = 0; i < 3; i++) {
  97  |     await page.evaluate(() => window.worldQA!.moveTo(-600, -700));
  98  |     await ready(page);
  99  |     await page
  100 |       .getByRole("button", { name: "Inspect RQ-4", exact: true })
  101 |       .click();
  102 |     await ready(page);
  103 |     const renderer = (await page.evaluate(() => window.worldQA!.metrics()))
  104 |       .renderer;
  105 |     expect(renderer.geometries).toBe(baseline.geometries);
  106 |     expect(renderer.textures).toBe(baseline.textures);
  107 |   }
  108 |   writeFileSync(
  109 |     "artifacts/sf04/browser/acceptance.json",
  110 |     JSON.stringify(
  111 |       {
  112 |         fractions,
  113 |         sensors,
  114 |         metrics: await page.evaluate(() => window.worldQA!.metrics()),
  115 |         errors,
  116 |       },
  117 |       null,
  118 |       2,
  119 |     ),
  120 |   );
  121 |   expect(errors).toEqual([]);
  122 | });
  123 | 
  124 | test("missing or corrupt asset fails by name and reason, without a substitute", async ({
  125 |   page,
  126 | }) => {
  127 |   await page.route("**/catalog/rq4.glb", (route) =>
  128 |     route.fulfill({ status: 404, body: "missing" }),
  129 |   );
  130 |   await page.goto("/?view=world&site=aerodrome&qa=1");
  131 |   await expect(page.getByRole("alert")).toContainText("rq4: HTTP 404", {
  132 |     timeout: 45000,
  133 |   });
  134 |   await expect(page.locator(".world-canvas")).toHaveAttribute(
  135 |     "data-ready",
  136 |     "false",
  137 |   );
  138 |   await page.unroute("**/catalog/rq4.glb");
  139 |   await page.route("**/catalog/f16.glb", (route) =>
  140 |     route.fulfill({ status: 200, body: "corrupt" }),
  141 |   );
  142 |   await page.reload();
  143 |   await expect(page.getByRole("alert")).toContainText(
  144 |     "f16: GLB integrity mismatch",
  145 |     { timeout: 45000 },
  146 |   );
  147 |   await page.unroute("**/catalog/f16.glb");
  148 |   await page.route("**/catalog/rq4.metadata.json", (route) =>
  149 |     route.fulfill({ status: 404, body: "missing" }),
  150 |   );
  151 |   await page.reload();
  152 |   await expect(page.getByRole("alert")).toContainText(
  153 |     "rq4: metadata HTTP 404",
  154 |     { timeout: 45000 },
  155 |   );
  156 |   await page.unroute("**/catalog/rq4.metadata.json");
  157 |   await page.route("**/catalog/catalog.json", async (route) => {
  158 |     const response = await route.fetch();
  159 |     const catalog = await response.json();
  160 |     catalog.assets = catalog.assets.filter(
  161 |       (a: { asset_id: string }) => a.asset_id !== "rq4",
  162 |     );
  163 |     await route.fulfill({ json: catalog });
  164 |   });
  165 |   await page.reload();
  166 |   await expect(page.locator(".world-canvas [role=alert]")).toContainText(
  167 |     "rq4: required catalog record is missing",
  168 |   );
  169 |   expect(await page.evaluate(() => window.worldQA)).toBeUndefined();
  170 | });
  171 | 
```