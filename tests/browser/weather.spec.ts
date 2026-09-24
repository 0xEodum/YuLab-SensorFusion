import { test, expect } from "@playwright/test";

test("rain capture replays independent seeds and evolves saved thermal state", async ({ page, request }) => {
  test.setTimeout(240_000);
  await page.goto("/?view=world&site=aerodrome&qa=1");
  await expect.poll(() => page.evaluate(() => window.worldQA?.metrics().status.ready ?? false),
    { timeout: 45_000 }).toBe(true);
  await page.getByRole("button", { name: "Unobstructed F-16" }).click();
  await page.getByRole("button", { name: "Save rig pose" }).click();
  await page.getByLabel("Capture condition").selectOption("rain");
  await page.getByLabel("Weather severity").focus();
  await page.getByLabel("Weather severity").press("End");
  await page.getByLabel("Simulation tick").fill("100");
  await page.getByLabel("weather noise seed").fill("11");
  const button = page.getByRole("button", { name: "Capture RGB, IR, LiDAR and references" });
  const capture = async () => {
    const accepted = page.waitForResponse((response) =>
      response.url().endsWith("/api/v1/captures") && response.request().method() === "POST");
    await button.click();
    const job = await (await accepted).json();
    await expect.poll(async () => (await (await request.get(`/api/v1/jobs/${job.job_id}`)).json()).state,
      { timeout: 120_000 }).toBe("succeeded");
    await expect(page.getByRole("status", { name: "Capture status" })).toContainText("succeeded", { timeout: 120_000 });
    return (await (await request.get(`/api/v1/jobs/${job.job_id}`)).json()).result;
  };
  const first = await capture();
  expect(first.tick_s).toBe(100);
  expect(first.weather_calibration.version).toBe("weather-response.v1");
  expect(first.weather_calibration.ir_extinction_per_m).toBeGreaterThan(0);
  expect(first.lidar_calibration.response.particle_rate_per_m).toBeGreaterThan(0);
  expect(first.lidar_calibration.status_codes.particle).toBe(3);
  const pixels = page.getByRole("img", { name: /RGB capture/ });
  await expect(pixels).toBeVisible();
  await page.screenshot({ path: "artifacts/sf08/rain-desktop.png", fullPage: true });
  await page.getByLabel("rgb noise seed").fill("1");
  const second = await capture();
  expect(second.artifacts.rgb.sha256).not.toBe(first.artifacts.rgb.sha256);
  for (const key of ["depth", "instance", "ir_radiance", "lidar_xyz", "lidar_beam_status"])
    expect(second.artifacts[key].sha256).toBe(first.artifacts[key].sha256);
  await page.getByLabel("Thermal time behavior").selectOption("continued");
  await page.getByLabel("Simulation tick").fill("101");
  const submitted = page.waitForRequest((req) => req.url().endsWith("/api/v1/captures") && req.method() === "POST");
  const thirdPromise = capture();
  const continued = (await submitted).postDataJSON();
  const third = await thirdPromise;
  expect(continued.environment.thermal_history).toBe("continued");
  expect(continued.environment.thermal_state.sha256).toBe(second.artifacts.thermal_state.sha256);
  expect(continued.environment.simulation_time_s).toBe(101);
  expect(third.tick_s).toBe(101);
  const stateResponse = await request.get(`/api/v1/jobs/${
    (await page.getByRole("img", { name: /RGB capture/ }).getAttribute("src"))!.split("/")[4]
  }/artifacts/${third.artifacts.thermal_state.id}`);
  expect((await stateResponse.json()).simulation_time_s).toBe(101);
});
