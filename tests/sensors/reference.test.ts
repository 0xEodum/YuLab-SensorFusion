import test from "node:test";
import assert from "node:assert/strict";
import {
  decodeInstanceId,
  encodeInstanceId,
  flipRows,
  shouldCaptureObject,
} from "../../packages/sensors/src/index.ts";

test("24-bit instance IDs round trip exactly and reserve zero for background", () => {
  for (const id of [0, 1, 255, 256, 65_535, 65_536, 0xff_ff_ff]) {
    const rgb = encodeInstanceId(id);
    assert.equal(decodeInstanceId(rgb), id);
  }
  assert.deepEqual(encodeInstanceId(0), [0, 0, 0]);
  assert.throws(() => encodeInstanceId(-1), /instance ID/i);
  assert.throws(() => encodeInstanceId(0x1_00_00_00), /instance ID/i);
  assert.throws(() => decodeInstanceId([1, 2]), /three bytes/i);
  assert.throws(() => decodeInstanceId([1, -1, 2]), /three bytes/i);
});

test("GPU bottom-left rows are converted to the top-left image contract", () => {
  const source = new Uint8Array([
    7, 8, 9, 10, 11, 12,
    1, 2, 3, 4, 5, 6,
  ]);
  assert.deepEqual(
    [...flipRows(source, 2, 2, 3)],
    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
  );
  assert.throws(() => flipRows(source, 3, 2, 3), /dimensions/i);
});

test("editor helpers, grids and decorative floors never enter sensor passes", () => {
  assert.equal(shouldCaptureObject({ visible: true, userData: {} }), true);
  for (const role of ["helper", "grid", "decorative-shadow-floor", "ui-overlay"])
    assert.equal(
      shouldCaptureObject({ visible: true, userData: { renderRole: role } }),
      false,
    );
  assert.equal(
    shouldCaptureObject({ visible: true, userData: { sensorExcluded: true } }),
    false,
  );
  assert.equal(shouldCaptureObject({ visible: false, userData: {} }), false);
});
